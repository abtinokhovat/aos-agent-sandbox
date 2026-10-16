// replay: run one normalized agent trajectory inside one sandbox runtime and record metrics.
//
//	replay -image IMG -runtime runc|runsc -steps steps.jsonl -out run.json \
//	       -task T -agent A -rep N [-warmup] [-step-timeout 300]
//
// One container per run: start -> steps -> teardown. Steps run sequentially via `docker exec`.
// Per-step metrics come from the container's cgroup v2 files (cpu.stat, io.stat, memory.*),
// which Docker (systemd cgroup driver) puts at /sys/fs/cgroup/system.slice/docker-<id>.scope.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Step struct {
	Step       int            `json:"step"`
	Kind       string         `json:"kind"`
	Command    *string        `json:"command"`
	Edit       map[string]any `json:"edit"`
	OrigExit   *int           `json:"orig_exit"`
	OrigOutSha *string        `json:"orig_out_sha"`
	LLMGapMs   *int           `json:"llm_gap_ms"`
}

type Counters struct {
	CPUUserUs, CPUSysUs                 int64
	IOReadB, IOWriteB, IOReadOps, IOWOp int64
	MemCurrent, MemPeak                 int64
}

type StepResult struct {
	Step         int     `json:"step"`
	Kind         string  `json:"kind"`
	Executed     bool    `json:"executed"`
	LatencyMs    float64 `json:"latency_ms"`  // outer: docker exec start to finish
	InnerMs      float64 `json:"inner_ms"`    // inside the shell, around the command only
	CPUUserMs    float64 `json:"cpu_user_ms"` // cgroup delta
	CPUSysMs     float64 `json:"cpu_sys_ms"`
	IOReadBytes  int64   `json:"io_read_bytes"`
	IOWriteBytes int64   `json:"io_write_bytes"`
	IOReadOps    int64   `json:"io_read_ops"`
	IOWriteOps   int64   `json:"io_write_ops"`
	MemCurrentMB float64 `json:"mem_current_mb"`
	MemPeakMB    float64 `json:"mem_peak_mb"` // cumulative since container start (kernel cannot reset memory.peak on 6.8)
	Procs        int     `json:"procs_spawned"`
	ExitCode     int     `json:"exit_code"`
	TimedOut     bool    `json:"timed_out"`
	OutSha       string  `json:"out_sha"`
	OutBytes     int     `json:"out_bytes"`
	OutHead      string  `json:"out_head"`
	OrigExit     *int    `json:"orig_exit"`
	ExitMatch    *bool   `json:"exit_match"`
	OutMatch     *bool   `json:"out_match"`
	LLMGapMs     *int    `json:"llm_gap_ms"`
	Command      string  `json:"command,omitempty"`
	Error        string  `json:"error,omitempty"`
}

type Run struct {
	Task, Agent, Runtime string
	Rep                  int
	Warmup               bool
	Image                string
	ContainerID          string
	StartMs              float64
	TeardownMs           float64
	TotalMs              float64
	StepsMs              float64
	Kernel               string
	StartedAt            string
	Steps                []StepResult
}

var meta = regexp.MustCompile(`(?m)^__AOS_META__ rc=(-?\d+) p0=(\d+) p1=(\d+) t0=([0-9.]+) t1=([0-9.]+) cwd=(.*)$`)

// PIDs are allocated sequentially in both runtimes' PID namespaces. A subshell's $BASHPID before and
// after the command gives the number of processes the command spawned (the closing marker costs 1,
// subtracted in the parser). /proc/loadavg's last-pid field is not populated by gVisor.
const prelude = `p0=$(echo $BASHPID)
t0=$EPOCHREALTIME
__aos_end(){ rc=$?; t1=$EPOCHREALTIME; p1=$(echo $BASHPID); printf '\n__AOS_META__ rc=%s p0=%s p1=%s t0=%s t1=%s cwd=%s\n' "$rc" "$p0" "$p1" "$t0" "$t1" "$PWD"; }
trap __aos_end EXIT
`

func sha(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }

func normSha(s string) string {
	s = strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\r", "\n")
	return sha([]byte(strings.TrimRight(s, " \t\r\n")))
}

func readInts(path string) map[string]int64 {
	out := map[string]int64{}
	b, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	for _, ln := range strings.Split(string(b), "\n") {
		f := strings.Fields(ln)
		if len(f) == 2 {
			if v, e := strconv.ParseInt(f[1], 10, 64); e == nil {
				out[f[0]] = v
			}
		}
	}
	return out
}

func readCounters(cg string) Counters {
	var c Counters
	cs := readInts(filepath.Join(cg, "cpu.stat"))
	c.CPUUserUs, c.CPUSysUs = cs["user_usec"], cs["system_usec"]
	if b, err := os.ReadFile(filepath.Join(cg, "io.stat")); err == nil {
		for _, ln := range strings.Split(string(b), "\n") {
			for _, kv := range strings.Fields(ln) {
				p := strings.SplitN(kv, "=", 2)
				if len(p) != 2 {
					continue
				}
				v, _ := strconv.ParseInt(p[1], 10, 64)
				switch p[0] {
				case "rbytes":
					c.IOReadB += v
				case "wbytes":
					c.IOWriteB += v
				case "rios":
					c.IOReadOps += v
				case "wios":
					c.IOWOp += v
				}
			}
		}
	}
	rd := func(n string) int64 {
		b, _ := os.ReadFile(filepath.Join(cg, n))
		v, _ := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
		return v
	}
	c.MemCurrent, c.MemPeak = rd("memory.current"), rd("memory.peak")
	return c
}

func docker(ctx context.Context, stdin []byte, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "docker", args...)
	var buf bytes.Buffer
	cmd.Stdout, cmd.Stderr = &buf, &buf
	if stdin != nil {
		cmd.Stdin = bytes.NewReader(stdin)
	}
	err := cmd.Run()
	return buf.Bytes(), err
}

func main() {
	image := flag.String("image", "", "docker image")
	runtime := flag.String("runtime", "runc", "runc|runsc")
	stepsF := flag.String("steps", "", "normalized steps jsonl")
	outF := flag.String("out", "", "output run json (must not exist)")
	task := flag.String("task", "", "task id")
	agent := flag.String("agent", "", "agent name")
	rep := flag.Int("rep", 0, "repetition index")
	warm := flag.Bool("warmup", false, "mark as warm-up (discarded in analysis)")
	stepTO := flag.Int("step-timeout", 300, "per-step timeout seconds")
	editor := flag.String("editor", "harness/replay/editor.py", "editor.py path on host")
	persist := flag.Bool("persist-cwd", false, "carry cwd between steps (persistent-shell agents); mini-swe-agent runs each command fresh")
	utf8 := flag.Bool("utf8", true, "set LANG/LC_ALL=C.UTF-8 (original mini-swe-agent runs had no UTF-8 locale; SWE-agent's did)")
	flag.Parse()

	var steps []Step
	f, err := os.Open(*stepsF)
	if err != nil {
		fatal(err)
	}
	dec := json.NewDecoder(f)
	for dec.More() {
		var s Step
		if err := dec.Decode(&s); err != nil {
			fatal(err)
		}
		steps = append(steps, s)
	}
	if _, err := os.Stat(*outF); err == nil {
		fatal(fmt.Errorf("%s exists; raw files are never overwritten", *outF))
	}

	run := Run{Task: *task, Agent: *agent, Runtime: *runtime, Rep: *rep, Warmup: *warm, Image: *image,
		StartedAt: time.Now().UTC().Format(time.RFC3339)}
	ctx := context.Background()
	name := fmt.Sprintf("aos_%s_%d", *runtime, os.Getpid())

	// ---- start
	tAll := time.Now()
	t0 := time.Now()
	out, err := docker(ctx, nil, "run", "-d", "-i", "--runtime="+*runtime, "--name", name, *image, "sleep", "infinity")
	if err != nil {
		fatal(fmt.Errorf("docker run: %v: %s", err, out))
	}
	run.ContainerID = strings.TrimSpace(string(out))
	defer func() { docker(ctx, nil, "rm", "-f", name) }()
	if o, err := docker(ctx, nil, "exec", name, "true"); err != nil { // first exec = ready
		fatal(fmt.Errorf("ready probe: %v: %s", err, o))
	}
	run.StartMs = ms(time.Since(t0))
	cg := "/sys/fs/cgroup/system.slice/docker-" + run.ContainerID + ".scope"
	if _, err := os.Stat(cg); err != nil {
		fatal(fmt.Errorf("cgroup path missing: %s", cg))
	}
	if k, err := docker(ctx, nil, "exec", name, "uname", "-r"); err == nil {
		run.Kernel = strings.TrimSpace(string(k))
	}
	// editor is installed outside the measured steps. `docker cp` does not reach a gVisor sandbox's
	// rootfs, so pipe it through exec (works for both runtimes).
	edSrc, err := os.ReadFile(*editor)
	if err != nil {
		fatal(err)
	}
	if o, err := docker(ctx, edSrc, "exec", "-i", name, "sh", "-c", "cat > /tmp/aos_editor.py"); err != nil {
		fatal(fmt.Errorf("install editor: %v: %s", err, o))
	}

	// Environment of a conda-activated login shell, captured once so each step can use plain
	// `bash -c` (re-running the login/conda activation per step costs ~110 ms CPU and would swamp small steps).
	var envArgs []string
	base := envMap(docker(ctx, nil, "exec", name, "env"))
	login := envMap(docker(ctx, nil, "exec", name, "bash", "-lc", "env"))
	for k, v := range login {
		if k == "_" || k == "SHLVL" || k == "PWD" || k == "OLDPWD" || k == "HOSTNAME" {
			continue
		}
		if bv, ok := base[k]; !ok || bv != v {
			envArgs = append(envArgs, "-e", k+"="+v)
		}
	}

	// Environment the original scaffolds set (mini-swe-agent and SWE-agent configs) plus a UTF-8
	// locale (the originals' outputs contain non-ASCII; py3.6 without a locale raises UnicodeEncodeError).
	for _, kv := range []string{"PAGER=cat", "MANPAGER=cat", "LESS=-R", "PIP_PROGRESS_BAR=off", "TQDM_DISABLE=1"} {
		envArgs = append(envArgs, "-e", kv)
	}
	if *utf8 {
		envArgs = append(envArgs, "-e", "LANG=C.UTF-8", "-e", "LC_ALL=C.UTF-8")
	}

	// ---- steps
	cwd := "/testbed"
	tSteps := time.Now()
	for _, st := range steps {
		r := StepResult{Step: st.Step, Kind: st.Kind, OrigExit: st.OrigExit, LLMGapMs: st.LLMGapMs}
		if st.Kind == "skip" || (st.Kind == "shell" && st.Command == nil) {
			run.Steps = append(run.Steps, r)
			continue
		}
		r.Executed = true
		sctx, cancel := context.WithTimeout(ctx, time.Duration(*stepTO)*time.Second)
		before := readCounters(cg)
		ts := time.Now()
		var raw []byte
		var xerr error
		if st.Kind == "shell" {
			r.Command = *st.Command
			script := fmt.Sprintf("cd %q 2>/dev/null || true\n%s%s\n", cwd, prelude, *st.Command)
			args := append(append([]string{"exec"}, envArgs...), name, "bash", "-c", script)
			raw, xerr = docker(sctx, nil, args...)
		} else { // edit
			req, _ := json.Marshal(st.Edit)
			r.Command = "edit:" + fmt.Sprint(st.Edit["command"]) + " " + fmt.Sprint(st.Edit["path"])
			raw, xerr = docker(sctx, req, "exec", "-i", name, "/opt/miniconda3/bin/python", "/tmp/aos_editor.py")
		}
		r.LatencyMs = ms(time.Since(ts))
		after := readCounters(cg)
		timedOut := sctx.Err() == context.DeadlineExceeded
		cancel()

		r.CPUUserMs = float64(after.CPUUserUs-before.CPUUserUs) / 1000
		r.CPUSysMs = float64(after.CPUSysUs-before.CPUSysUs) / 1000
		r.IOReadBytes, r.IOWriteBytes = after.IOReadB-before.IOReadB, after.IOWriteB-before.IOWriteB
		r.IOReadOps, r.IOWriteOps = after.IOReadOps-before.IOReadOps, after.IOWOp-before.IOWOp
		r.MemCurrentMB, r.MemPeakMB = float64(after.MemCurrent)/1e6, float64(after.MemPeak)/1e6
		r.TimedOut = timedOut

		body := string(raw)
		if st.Kind == "shell" {
			if m := meta.FindStringSubmatch(body); m != nil {
				r.ExitCode, _ = strconv.Atoi(m[1])
				p0, _ := strconv.Atoi(m[2])
				p1, _ := strconv.Atoi(m[3])
				a, _ := strconv.ParseFloat(m[4], 64)
				b, _ := strconv.ParseFloat(m[5], 64)
				r.Procs, r.InnerMs = p1-p0-1, (b-a)*1000
				if *persist {
					cwd = m[6]
				}
				body = body[:strings.Index(body, "\n__AOS_META__")]
			} else {
				r.Error = "no meta marker"
				r.ExitCode = -1
			}
		} else if xerr != nil {
			if ee, ok := xerr.(*exec.ExitError); ok {
				r.ExitCode = ee.ExitCode()
			} else {
				r.ExitCode = -1
			}
		}
		if timedOut {
			r.ExitCode = 124
			r.Error = "step timeout"
		}
		r.OutBytes = len(body)
		r.OutSha = normSha(body)
		r.OutHead = body
		if len(r.OutHead) > 2048 {
			r.OutHead = r.OutHead[:2048]
		}
		if st.OrigExit != nil {
			v := *st.OrigExit == r.ExitCode
			r.ExitMatch = &v
		}
		if st.OrigOutSha != nil && st.Kind == "shell" {
			v := *st.OrigOutSha == r.OutSha
			r.OutMatch = &v
		}
		run.Steps = append(run.Steps, r)
	}
	run.StepsMs = ms(time.Since(tSteps))

	// ---- teardown
	t1 := time.Now()
	docker(ctx, nil, "rm", "-f", name)
	run.TeardownMs = ms(time.Since(t1))
	run.TotalMs = ms(time.Since(tAll))

	b, _ := json.MarshalIndent(run, "", " ")
	if err := os.MkdirAll(filepath.Dir(*outF), 0o755); err != nil {
		fatal(err)
	}
	if err := os.WriteFile(*outF, b, 0o444); err != nil {
		fatal(err)
	}
	fmt.Printf("%s %s %s rep%d: start=%.0fms steps=%.0fms teardown=%.0fms\n", *task, *agent, *runtime, *rep, run.StartMs, run.StepsMs, run.TeardownMs)
}

func envMap(b []byte, _ error) map[string]string {
	m := map[string]string{}
	for _, ln := range strings.Split(string(b), "\n") {
		if i := strings.Index(ln, "="); i > 0 {
			m[ln[:i]] = ln[i+1:]
		}
	}
	return m
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "replay:", err)
	os.Exit(1)
}
