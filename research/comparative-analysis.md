# Comparative and Critical Analysis: OS Support for LLM Agent Sandboxes

Papers reviewed (all in `research/`):

| # | Study | Venue / ID | Authors (affiliation) |
|---|---|---|---|
| S1 | **DeltaBox**: Scaling Stateful AI Agents with Millisecond-Level Sandbox Checkpoint/Rollback | arXiv 2605.22781v2 (cs.OS) | Dong et al. (SJTU, Huawei) |
| S2 | **AgenticOS**: An Intent-Oriented Secure Operating System Architecture for Autonomous AI Agents | arXiv 2606.21129v1 (cs.CR) | Zhao et al. (Tencent) |
| S3 | **ActPlane**: Programmable OS-Level Policy Enforcement for Agent Harnesses | arXiv 2606.25189v2 (cs.OS) | Zheng et al. (UC Santa Cruz, Virginia Tech, HKUST, Alibaba) |
| S4 | **SpecBox**: Speculative Sandbox Scheduling for Efficient LLM Agent Serving | arXiv 2607.23933v2 (cs.DC) | Zhang et al. (Beihang, Leeds, Sydney) |

---

## Table 1. Comparative Analysis

| Study | Objective | Methodology | Key Findings | Limitations |
|---|---|---|---|---|
| **S1 DeltaBox** | Make checkpoint/rollback (C/R) of the *whole* sandbox state (files and process memory) fast enough for tree search (MCTS, Best-of-N) and RL rollout fan-out. In these workloads, rollback sits on the critical path. | **New OS abstraction (DeltaState)** that saves only the changes between checkpoints.<br>• **DeltaFS:** modified overlayfs (~565 lines of C) that freezes the writable layer and inserts a new one without unmounting. XFS reflink gives 4 KB copy-on-write.<br>• **DeltaCR** (~1.2K lines of Python): background CRIU dump plus `fork()` of a frozen "template" process for fast restore.<br>• **Network Proxy Daemon:** keeps LLM connections out of the agent process.<br>• Runs in a Firecracker microVM.<br>• **Evaluation:** replayed SWE-bench Verified MCTS trajectories (Qwen3-Coder-30B) against replay+copy, Firecracker diff snapshots, CRIU+copy, E2B, and CubeSandbox. | • Checkpoint takes **10.83 ms** and is hidden under LLM inference. Restore takes **1.86 ms** (fast path) or 9.29 ms (slow path) (Table 4).<br>• E2B restore is about **480× slower** (Table 2).<br>• State management is **1–2 %** of end-to-end time, vs **23–48 %** for E2B (Fig. 6).<br>• RL fan-out: GPU occupancy is **95–97 %** vs 77–80 % (CubeSandbox) and 29–36 % (E2B) (Fig. 7).<br>• `fork` latency is 0.57 ms at N=1 and 5.47 ms at N=64 (Table 3).<br>• Reachability-aware GC cuts dump storage by 46–63 %. | • Cannot roll back network I/O or other external side effects.<br>• Agent code must be restructured: LLM SDK moved to a proxy, a single-threaded worker, and quiescent fork points. This weakens the "agent transparency" claim (R4).<br>• Needs a custom guest-kernel module and XFS with reflink.<br>• Template pool uses memory. An evicted template falls back to the 5× slower path.<br>• Evaluated on replayed traces (24 MCTS trajectories, mainly one model) on a single 96-core server. |
| **S2 AgenticOS** | Redesign OS security for autonomous agents. The OS moves from "resource manager + permission checks" to an **"intent filter"**. Goal: an agent compromised by prompt injection, supply-chain poisoning, or poisoned tool output cannot combine POSIX primitives into actions beyond the user's task. | **Conceptual architecture (position paper); no prototype.** Four layers:<br>• **Ghost Kernel:** minimal, verifiable, exposes no syscalls.<br>• **Logic Shutter:** intent mediation, capability tokens, information-flow (IFC) labels, audit.<br>• **Agent Capsule:** Manifest-only runtime with no `fork/exec/mmap/socket`.<br>• **Semantic Boundary Gateway:** protocol proxy and credential holder.<br>Also introduces an **Intent ABI** (6 families, e.g. `FetchJSON`, `RunUnitTest`), the **Weaver** builder, and a Skill admission pipeline. Validation is a qualitative security analysis against a stated threat model. | • Argues syscall-based escape paths are *structurally removed*, under its assumptions (§5.1).<br>• The attack surface shrinks to a narrow, auditable set of semantic interfaces.<br>• Names the residual risks: capability-composition chains (`FetchJSON → ModelSummarize → UploadArtifact`), intent drift, and covert channels (timing, size, presence, content selection).<br>• Proposes mitigations: IFC labels, intent-interaction graphs, request-timing normalization, output padding.<br>• Frames "human approval" as a first-class ABI call. | • **No implementation or experiments**, so every claim is unvalidated.<br>• Drops POSIX, so existing software cannot run unmodified (§7.3).<br>• Each call crosses up to 4 layers. The authors acknowledge the overhead but do not quantify it (§7.2).<br>• Relies on strong assumptions: a trusted Ghost Kernel, trusted Manifests and policy inputs, unbroken cryptography.<br>• The Logic Shutter has a large trusted computing base.<br>• Intent is undecidable in general (§7.1), and end-to-end formal verification is left as future work. |
| **S3 ActPlane** | Enforce harness policies deterministically at the OS level (e.g. "run tests before commit", "never delete data"). This includes indirect paths (scripts, subprocesses) that tool-call guardrails miss. The engine returns *semantic* feedback so the agent can recover. | **Empirical study:** 64 repositories, 2,116 statements from CLAUDE.md/AGENTS.md files.<br>**Policy language:** a small IFC DSL (source → target, effect `block/kill/notify`, temporal and lineage gates, `because` reason) that the **agent writes itself**.<br>**Engine:** Rust compiler (~3.2K LoC) → eBPF engine (~1.8K LoC; BPF-LSM plus tracepoints, 64-bit label bitmasks).<br>**Isolation:** hierarchical policy domains stop agents from weakening higher-authority rules.<br>**Evaluation:**<br>• RQ1: 607-policy translation<br>• RQ2: 190-trace benchmark vs prompt-filter, tool-regex, FIDES, and ActPlane-opaque<br>• RQ3: overhead<br>• RQ4: OctoBench (21 tasks)<br>• RQ5: OpenAgentSafety (361 tasks) | • 64 % of statements are policies, 83 % are system-observable, and 16 % are cross-event. 73.6 % need project or task context.<br>• An LLM translated **all 607** policies (2 needed a retry) at **$0.028 per policy**.<br>• Decision compliance is **75.8 %** vs 45.3–53.7 % for the baselines. On *hidden* traces it is 74 % vs **0 %** for tool-level baselines (Table 2, Fig. 12).<br>• Semantic feedback gives 3× more correct violation outcomes than the opaque ablation (86 vs 27).<br>• Overhead is **1.9 %** (agent traces) and 6.5 % (kernel build) with 32 rules, and < 8.4 % with 100 rules.<br>• Prevents **74 %** (78/106) of baseline-unsafe behaviors on OpenAgentSafety. | • Covers only per-event and cross-event policies (~45 % of the dataset). Content and semantic-only policies are out of scope.<br>• More false positives than the opaque engine (18 vs 1). 17 of the 18 come from over-broad LLM-written rules.<br>• Semantically equivalent actions evade command-matching rules (e.g. a custom git client).<br>• Monotonic labels cause over-tainting.<br>• Service-side effects (WebDAV, databases) are missed.<br>• Kernel or CAP_BPF compromise is out of scope.<br>• Linux-only, max 128 rules.<br>• Traces are LLM-generated and outcomes are scored by an LLM judge. |
| **S4 SpecBox** | Resolve the trade-off between **reserved** (always-on) tool sandboxes, which waste memory, and **on-demand** sandboxes, which add cold-start tail latency, for multi-tenant agents calling MCP tool sandboxes. | **User-space runtime middleware** on AgentScope (Python, Docker sandboxes). Three mechanisms:<br>1. **Intent-aware prewarming:** keyword router (γ = 2) plus TF-IDF semantic router read the *streaming* LLM tokens. The two routers' candidate sets are combined by union.<br>2. **Stochastic prefetching:** first-order Markov model over a sandbox dependency graph (Laplace smoothing, τ = 0.6, budget B = 1).<br>3. **Semantic result cache** plus **out-of-band shared-memory** artifact transfer.<br>**Evaluation:** 200 multi-turn traces built from MCPBench (32 MCP servers), Qwen3.5-Max API, QPS 1–20, vs Reserved and On-demand. | • P99 end-to-end latency is **88.7 s vs 257.2 s** for On-demand at QPS = 20 (**2.9×**).<br>• Cumulative provisioning latency is **4.53×** lower than On-demand and within 10.6 % of Reserved.<br>• Peak memory is **49.4 GiB vs 80.6 GiB** for Reserved (−45.9 %). Peak CPU is −23 %.<br>• Routing: Micro-F1 0.970. Union assembly gives 124 ms wait with 5 % cold starts (Table 3).<br>• Prefetching cuts per-turn wait from 583 ms to 97 ms by turn 10 (6×).<br>• Semantic cache: 2.91× lower wait, 37.4 % hit rate.<br>• Out-of-band transfer of 1 GB takes 5.97 ms vs 1,873 ms over JSON-RPC (313×). | • The first-order Markov predictor degrades on long, open-ended workflows and gives no benefit on turn 1.<br>• The shared-memory path requires co-location on one host, so it cannot scale a session across nodes.<br>• Semantic cache reuse is safe only for deterministic tools, so stale or wrong results are a risk.<br>• Threat model excludes malicious agents and sandbox escapes.<br>• Evaluated on a single 16-core server with LLM-generated traces and only 2 baselines (no prior predictive prewarmers such as IceBreaker).<br>• Presentation inconsistencies: the system is named "PredBox"/"Laplace" in figures, and the cache threshold is 0.6 in Table 4 vs 0.8 in the text. |

---

## Table 2. Critical Analysis (Qualitative Dimensions)

| Study | Complexity | Scalability | Expertise Requirements | Flexibility | Runtime Overhead | Evidence Strength |
|---|---|---|---|---|---|---|
| **S1 DeltaBox** | **High.** Kernel-level filesystem changes, CRIU, template pool, async-warm thread, network proxy, host/guest StateManager, and a consistency protocol. Many tightly coupled parts. | **Strong within one VM:** 64 forked children in 5.47 ms p50, ~11 MB RSS per child, many agents per VM. Snapshot storage grows with the search tree, so GC is needed. Only single-node results. | **Very high for builders:** overlayfs internals, CRIU/userfaultfd, Firecracker, XFS reflink. Agent developers must adapt their code (proxy daemon, single-threaded worker). | **Medium.** Supports linear, Best-of-N, MCTS, and RL. LangGraph adapter. Claims the design also applies to containers. Tied to CRIU-dumpable processes and an in-sandbox agent. | Low on the critical path: ~11 ms SIGSTOP hidden under inference, 1.86 ms restore. Costs memory (templates) and storage (dumps). | **Strong.** 5 baselines, component breakdown, RL case study. Limited by replayed traces and a small trajectory set. |
| **S2 AgenticOS** | **Very high (and unbuilt).** A whole new OS stack: verified micro-kernel, policy engine, capsule runtime (WASM/eBPF/CHERI), gateway, Weaver builder, Skill admission. Replaces POSIX. | **Unknown.** Never measured. Per-call mediation across 4 layers and fixed-window request batching would likely add latency. | **Highest:** formal verification (seL4-style), capability security, TEEs, IFC. Developers must write Manifests, possibly use a restricted DSL, and port tools into Skills. | **Low for existing software** (no POSIX), **high for policy expressiveness** (Manifests, IFC rules, human-approval points). Skills can grow only through admission. | Acknowledged to be higher than syscalls (§7.2), not quantified. | **Weak.** Conceptual only. No prototype, benchmark, or case study. |
| **S3 ActPlane** | **Moderate.** ~5K LoC. Loads eBPF into a stock Linux kernel; no kernel patching. DSL compiler plus runner. | **Good per host:** up to 128 concurrent rules. Per-syscall cost grows with rule count (`open` 0.58 → 13.4 µs at 100 rules), but end-to-end overhead stays < 8.4 %. Policy domains isolate many agents on one host. | **Low for policy authors** (LLM agents write rules; mean 71 tokens per policy). **Moderate for operators:** BPF-LSM kernel, root/CAP_BPF, and human review of higher-authority rules. | **High.** Harness-agnostic (evaluated under Codex and OpenHands). Supports runtime policy deltas. Covers per-event and cross-event rules, but not content or semantic policies. | **1.9–8.4 %** end-to-end; hot reload in 26 µs. | **Strong and broad.** Empirical study, 5 research questions, 2 external benchmarks, cross-model replication (κ = 0.822). Relies on LLM-generated traces and an LLM judge. |
| **S4 SpecBox** | **Low–moderate.** User-space Python middleware: two routers, a Markov model, a cache, and shared memory. No kernel or sandbox changes. | **Designed for multi-tenant scale.** Latency stays bounded at QPS 1–20, where On-demand provisioning exceeds 50 s. Cross-node scaling is blocked by the mmap co-location requirement. | **Moderate:** agent-framework integration plus tuning of many thresholds (γ, τ, λ, B, τc). No kernel knowledge needed. | **Medium–high.** Needs only streaming tokens and MCP. Only AgentScope is implemented. Applicability to RL rollouts is claimed, not shown. | Tens of µs of control-plane work. Wrong prewarms waste memory and CPU (5 % cold starts with union assembly). | **Moderate.** Real MCP servers, a concurrency sweep, and per-mechanism ablations. Single server, synthetic traces, weak baselines, naming inconsistencies. |

---

## Critical Analysis

### 1. Similarities

- **The system layer under the model, not the model itself, is where all four papers fix agent problems.** Each argues that prompt-level or framework-level fixes are not enough:
  - DeltaBox: LangGraph checkpoints "cannot undo physical OS-level side effects" (§4.4).
  - ActPlane: tool-call guardrails miss subprocesses (§2.3).
  - AgenticOS: prompt filtering and tool allowlists are insufficient (§1.1).
  - SpecBox: serving engines are "oblivious to the physical host-plane environment" (§7).
- **Three of the four hide their cost inside the LLM inference window.**
  - DeltaBox runs its checkpoint under 1–9 s of inference, so the agent sees no blocking (Table 4).
  - SpecBox overlaps sandbox boot with token generation.
  - ActPlane notes that its per-tool-call overhead is "5–6 orders of magnitude smaller than a single LLM inference turn" (§5.4).

  The shared insight: LLM latency dominates agent workloads, so seconds of idle time are available for systems work.
- **AgenticOS and ActPlane share a security vocabulary.** Both use information-flow labels, capability or authority hierarchies, and human/higher-authority rules that the agent cannot weaken. Both also flag *composition* attacks, where individually legal actions are chained into a violation: AgenticOS §5.2 and ActPlane's cross-event rules.
- **DeltaBox and SpecBox are both sandbox-lifecycle performance papers.**
  - Both evaluate by replaying recorded traces rather than running live agents.
  - Both list RL rollouts as a target workload.
  - Both trade memory for latency (warm templates vs prewarmed containers).

### 2. Differences

| Dimension | DeltaBox | AgenticOS | ActPlane | SpecBox |
|---|---|---|---|---|
| Primary goal | Performance (state C/R) | Security (isolation) | Safety/compliance (policy) | Performance (provisioning) |
| Layer modified | Guest kernel FS + userspace | Entire OS | Kernel via eBPF (no patch) | Userspace middleware |
| Approach | Evolutionary (Linux, Firecracker) | Revolutionary (drops POSIX) | Evolutionary (stock Linux) | Evolutionary (Docker, MCP) |
| Sandbox model | One deep stateful sandbox | Capsule per agent | Process tree on host | Many short-lived tool sandboxes |
| When policy/state is decided | At each search step | **Before start** (static Manifest) | **At runtime** (agent-written, refinable) | Online prediction from token stream |
| Validation | Prototype + benchmarks | None | Prototype + benchmarks + empirical study | Prototype + benchmarks |

The sharpest contrast is between **AgenticOS and ActPlane**, which target the same problem (stopping an agent from acting outside its mandate) with opposite assumptions:

- **AgenticOS** requires a complete Manifest *before* the agent starts and removes every interface not listed in it.
- **ActPlane's empirical study** shows that **73.6 %** of system-observable policies, and **95 %** of cross-event policies, depend on project or task context that cannot be written statically (Takeaway #3). ActPlane therefore lets the agent write and refine rules at runtime: 110 runtime deltas over 21 OctoBench tasks.

ActPlane's data is therefore direct evidence of a cost AgenticOS does not measure: writing correct up-front Manifests is hard. AgenticOS, in turn, gives far stronger guarantees in principle. ActPlane explicitly leaves kernel compromise and CAP_BPF compromise out of scope, and agent-authored rules give only "compliance assistance under a cooperative-but-fallible model" (§3.1).

### 3. Strengths and Weaknesses (Pros / Cons)

**S1 DeltaBox**
- ✅ Orders-of-magnitude gains with clear attribution. Each component's cost is broken down (Table 4).
- ✅ Fixes a real correctness issue: it restores files and memory *together*. The authors show that filesystem-only rollback causes semantic inconsistency (§2.2).
- ✅ Production-relevant RL result: 95–97 % GPU occupancy vs 29–36 % for E2B.
- ❌ Not truly transparent. Agents must route LLM traffic through the proxy daemon, and Python SDK threads break `fork` (§4.2.3).
- ❌ External side effects (network calls, pushed commits) cannot be rolled back, which is exactly what makes some agent actions dangerous.
- ❌ Depends on specific infrastructure (custom overlayfs module, XFS reflink, CRIU compatibility).

**S2 AgenticOS**
- ✅ Most ambitious and principled security model. It builds on established ideas (capabilities, seL4, IFC) and is candid about residual risks such as covert channels and intent drift.
- ✅ Treating human approval as a first-class ABI call gives a clean way to assign responsibility (§7.5).
- ❌ No implementation and no measurement. Every benefit is argued, not shown.
- ❌ Breaking POSIX compatibility is a large adoption barrier. Most agent tools (compilers, test runners, git) would need to be rewritten as Skills.
- ❌ The Logic Shutter centralizes a large, complex trusted computing base, which partly undoes the minimal-kernel argument (§5.5).

**S3 ActPlane**
- ✅ Grounded in data. The empirical study on 64 repositories justifies every design requirement.
- ✅ Catches what the alternatives cannot: 74 % vs 0 % on hidden-path violations, at ≤ 8.4 % overhead.
- ✅ Semantic feedback is shown by ablation to matter: correct violation outcomes rise from 27 to 86.
- ✅ Open source, and runs on a stock kernel.
- ❌ Covers only ~45 % of policies by design.
- ❌ Correctness depends on LLM-written rules: 17 of 18 false positives came from over-broad translations.
- ❌ Matching is on object names (e.g. `exec "git"`), so equivalent operations through other binaries evade command-based rules.
- ❌ Evaluation relies on an LLM judge and synthetic traces, so the results could carry LLM bias.

**S4 SpecBox**
- ✅ Simple to deploy: no kernel or sandbox changes, works with standard MCP.
- ✅ A good middle point between the two baselines: memory close to On-demand (49.4 vs 40.4 GiB), latency close to Reserved (within 10.6 %).
- ✅ Clear ablations for each mechanism (γ sensitivity, router models, assembly policy, cache, transport).
- ❌ Prediction quality depends on workflow regularity. A first-order Markov model ignores longer history.
- ❌ Semantic cache reuse risks returning stale results for tools whose outputs change over time. The paper limits reuse to "deterministic" tools but does not say how determinism is detected.
- ❌ Weaker experimental rigor: one server, two simple baselines, LLM-generated traces, and inconsistent naming and parameters across sections.

### 4. Trade-offs and Limitations

1. **Memory vs latency (DeltaBox, SpecBox).**
   - DeltaBox keeps frozen template processes in memory to get 1.86 ms restores. When a template is evicted, restore falls back to 9.29 ms.
   - SpecBox keeps speculative containers warm. Peak memory: Reserved 80.6 GiB, SpecBox 49.4 GiB, On-demand 40.4 GiB; SpecBox sits between the extremes.

   Both papers expose the trade-off through tunable budgets (template pool size N_tpl; prefetch budget B).
2. **Earliness vs accuracy (SpecBox).**
   - Keyword threshold γ = 1 triggers early but gives an 80 % match rate and 786 ms average wait.
   - γ = 3 gives a 97 % match rate but 622 ms wait.
   - γ = 2 is the sweet spot: 95 % match, 323 ms wait (Table 1).
   - Similarly, union assembly accepts 5 % cold starts for 3.16× lower wait than intersection (Table 3).
3. **Security strength vs compatibility (AgenticOS vs ActPlane).** AgenticOS removes whole interface classes but cannot run existing software. ActPlane runs anything on Linux but leaves gaps: equivalent operations, content policies, service-side effects, and kernel compromise.
4. **Detection vs false positives (ActPlane).** Semantic feedback lets agents recover, but broader rules raise false positives from 1 (opaque) to 18. Monotonic labels give complete history at the cost of over-tainting.
5. **Transparency vs required changes (DeltaBox).** The paper sets "no code changes" as requirement R4, yet fork-safety forces the LLM SDK out of the agent process.
6. **Generality vs evidence.**
   - SpecBox claims to be framework-agnostic and RL-ready but implements only AgentScope.
   - DeltaBox claims its optimizations apply to containers but evaluates only Firecracker.
   - AgenticOS makes the broadest claims with no evidence at all.

### 5. Gaps and Complementarity

The four systems address different layers and could be combined:
- DeltaBox's rollback could undo actions that ActPlane detects only *after* the fact (its `kill` effect is post-operation).
- SpecBox's prewarming could feed DeltaBox's warm templates.
- AgenticOS's gateway addresses the network side effects that DeltaBox explicitly cannot roll back.

No paper measures how the choice of **isolation runtime** affects these mechanisms, for example containers (runc) vs user-space kernels (gVisor) vs microVMs.

### 6. Relevance to This Project (Docker/runc vs gVisor workload characterization)

- **DeltaBox** uses the same workload source as this project (SWE-bench Verified trajectories, replayed without LLM calls). Its per-event C/R numbers are a useful reference point for per-step costs.
- **ActPlane** depends on host eBPF/BPF-LSM hooks. Under gVisor, the agent's syscalls are served by the Sentry rather than the host kernel. Our own notes show we had to use `runsc --strace` instead of bpftrace for this reason. ActPlane-style enforcement would therefore likely need a different hook point under gVisor. This is our inference; the paper does not test it.
- **SpecBox** measures cold-start latency with Docker sandboxes (2–4 s typical, up to ~20 s). Our runc vs runsc step timings (e.g. pilot: SWE-agent 11.5 s vs 26.5 s) suggest the isolation runtime would change the size of the cold-start window that SpecBox is trying to hide.
