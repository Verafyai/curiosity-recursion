# Related work for Curiosity Recursion v0.2

Paper version 0.1.1, 26 November 2026. Condensed reading notes behind the CR v0.2 upgrade.
Every source below was opened on 26 Nov 2026 (arXiv API metadata and abstract, PMLR v235 index,
Crossref, or the publisher page). Numbers are the authors' own reported results, quoted from the
abstract or post; nothing here is a CR measurement. BibTeX keys are in `refs.bib`.

CR v0.1.0 facts these notes respond to (from `results-values.tex` and `RESULTS.md`, answer key v1):
B5 recovered 9.8% of the full dossiers against 11.6% for B1 ReAct and 12.4% for post hoc B5-fix;
B5 precision 66.9% against 49.3% for B1; 41.4% of B5's calls and 52.7% of B5-max's were exact
repeats; B5 used about 17 to 23 of its 100 allowed calls; B3 calls came back empty 75.6% of the time;
the tools reach only archive.org, loc.gov and wikidata.org, so Homer (0/109 reachable) and John
(2/102 reachable) score 0 for every strategy.

## 1. Single-agent reasoning and acting

**ReAct** (Yao et al., ICLR 2023, arXiv:2210.03629, `yao2023react`). Interleaves reasoning traces with
tool actions in one trajectory. On ALFWorld and WebShop it beat imitation and RL baselines by 34 and 10
absolute points of success rate with one or two in-context examples. *For CR:* ReAct is B1, the bar to
beat; its strength in our data is breadth (almost no repeated calls), which CR v0.2 must match before its
precision can pay off.

**Reflexion** (Shinn et al., NeurIPS 2023, arXiv:2303.11366, `shinn2023reflexion`). The agent writes a
verbal reflection on each failed attempt into an episodic memory and reads it on the next attempt, with
no weight updates. It reports 91% pass@1 on HumanEval against 80% for GPT-4. *For CR:* after each round,
write short lessons ("FTS on '<surname> <town>' returns only a county history; stop", "spelling X found
the pension index") into a per-run reflection memory and feed them to the planner and lead scorer.

**Generative Agents** (Park et al., arXiv:2304.03442, `park2023generative`). Stores a full natural-language
record of experience, periodically synthesizes higher-level reflections, and retrieves them to plan; an
ablation shows observation, planning and reflection each matter. *For CR:* reflections should be compact
summaries over many ledger rows, not raw logs, so the planner's context stays small.

## 2. Search over branches, sampling and agreement

**Tree of Thoughts** (Yao et al., NeurIPS 2023, arXiv:2305.10601, `yao2023tot`). Searches over intermediate
"thoughts" with the model as evaluator, with lookahead and backtracking. On Game of 24 it solved 74% of
tasks against 4% for GPT-4 chain-of-thought. *For CR:* the question graph is already a tree; what it lacks
is an evaluator that ranks open questions so the best one is expanded next.

**LATS, Language Agent Tree Search** (Zhou et al., ICML 2024, PMLR 235, arXiv:2310.04406, `zhou2024lats`).
Monte Carlo tree search over agent trajectories, with a model-based value function, environment feedback
and self-reflection. Reports 92.7% pass@1 on HumanEval and an average score of 75.9 on WebShop. *For CR:*
the closest template for v0.2's lead expansion: select by UCT over a value score, expand, observe the real
tool result, back the reward up the tree.

**RAP** (Hao et al., EMNLP 2023, arXiv:2305.14992, `hao2023rap`). Uses the model as both agent and world
model inside MCTS; on plan generation, RAP on LLaMA-33B beat GPT-4 chain-of-thought by 33% relative.
*For CR:* a cheap "world model" prediction of expected yield (will this source likely hold this fact for
this era and place?) is enough to rank leads before spending a real call.

**UCT and UCB1** (Kocsis and Szepesvari, ECML 2006, `kocsis2006uct`; Auer, Cesa-Bianchi and Fischer,
Machine Learning 2002, `auer2002ucb`). Bandit-based tree search picks the child maximizing mean reward
plus an exploration bonus that shrinks with visits, with finite-time regret bounds. *For CR:* use UCB1 for
the budget allocator across viewpoints and record types, so a viewpoint that keeps returning nothing loses
budget automatically.

**Self-consistency** (Wang et al., ICLR 2023, arXiv:2203.11171, `wang2023selfconsistency`). Samples several
reasoning paths and keeps the most consistent answer: +17.9 points on GSM8K, +11.0 SVAMP, +12.2 AQuA.
*For CR:* when two independent workers reach the same fact from different sources, that agreement is a
verification signal; a fact supported by one snippet stays a lead.

**More Agents Is All You Need** (Li et al., TMLR, arXiv:2402.05120, `li2024moreagents`). Plain sampling and
voting improves with the number of agents, more on harder tasks. *For CR:* parallelism helps only if the
workers are not copies of one another; v0.2 splits workers by viewpoint and record type so votes are
independent.

**Multiagent debate** (Du et al., ICML 2024, PMLR 235, arXiv:2305.14325, `du2024debate`). Several model
instances propose answers and critique each other over rounds; the authors report better math and
strategic reasoning and fewer hallucinated facts (no single headline number in the abstract). *For CR:*
a cheap adversarial check in the merge step: a skeptic pass tries to refute each merged claim from the
quoted evidence before it is promoted.

## 3. Multi-agent and deep-research systems

**Anthropic, "How we built our multi-agent research system"** (Hadfield, Zhang, Lien, Scholz, Fox and
Ford, Anthropic Engineering blog, 13 June 2025, `anthropic2025multiagent`). An orchestrator plans and
spawns 3 to 5 parallel subagents, each with an objective, output format, tool guidance and task
boundaries. Multi-agent beat single-agent Claude Opus 4 by 90.2% on their internal research eval; on
BrowseComp, token usage alone explained 80% of performance variance (three factors explained 95%), and
multi-agent runs used about 15 times the tokens of a chat. Vague delegation made subagents duplicate work;
they also needed resumable execution for long-running agents. *For CR:* (a) give every worker an explicit
lane (viewpoint x record type x date window) so they do not overlap; (b) report a budget-matched
comparison, because more calls alone would explain gains; (c) Temporal already gives the resume behavior
they had to build.

**STORM** (Shao et al., NAACL 2024, arXiv:2402.14207, `shao2024storm`). Discovers diverse perspectives,
simulates perspective-guided question asking grounded in sources, then curates an outline. Editors judged
25% more of its articles organized and 10% more broad in coverage than an outline-driven retrieval
baseline. *For CR:* outline first: before any search, enumerate the dossier sections a genealogist would
expect (military, census, church, newspaper, land, probate, immigration) and generate questions per
section, so coverage gaps are visible from call 1.

**Co-STORM** (Jiang et al., EMNLP 2024, arXiv:2408.15232, `jiang2024costorm`). Several agents converse while
a dynamic mind map organizes what has been found; 70% of study participants preferred it to a search
engine and 78% to a RAG chatbot. *For CR:* the shared mind map is the shared ledger plus the outline:
every worker reads what others have covered before choosing a query.

**AutoGen** (Wu et al., arXiv:2308.08155, `wu2023autogen`). A framework for multi-agent conversation
programs. *For CR:* none needed; Temporal child workflows are the orchestration layer, which keeps
determinism and replay.

**Why Do Multi-Agent LLM Systems Fail? (MAST)** (Cemri et al., arXiv:2503.13657, `cemri2025mast`). 1600+
annotated traces from 7 frameworks; 14 failure modes in 3 groups (system design, inter-agent misalignment,
task verification); kappa 0.88 between annotators; gains over single agents are often minimal. *For CR:*
keep CR's verification step as a hard gate in the merge, and preregister ablations (no ledger, no
parallelism) so a swarm win cannot be credited to the wrong part.

**Search-o1** (Li et al., arXiv:2501.05366, `li2025searcho1`), **WebThinker** (Li et al., NeurIPS 2025,
arXiv:2504.21776, `li2025webthinker`), **DeepResearcher** (Zheng et al., arXiv:2504.03160,
`zheng2025deepresearcher`). Reasoning models that search when uncertain and condense documents before use
(Search-o1), interleave think, search and draft (WebThinker), or train research behavior with RL on the
live web, reporting up to 28.9 points over prompt-engineered baselines (DeepResearcher). *For CR:* the
"reason in documents" step matches CR's quote-grounded evidence extraction; RL training is out of scope
for v0.2 (no credits for training, and six subjects is far too few).

**Deep Research Agents survey** (Huang et al., arXiv:2506.18096, `huang2025drsurvey`). Taxonomy of static
vs dynamic workflows and single vs multi-agent designs; flags restricted external knowledge and sequential
execution inefficiency as key benchmark limits. *For CR:* both limits show up directly in v0.1.0
(reachability ceiling; serial calls).

## 4. Query reformulation and repeated search

**Rewrite-Retrieve-Read** (Ma et al., EMNLP 2023, arXiv:2305.14283, `ma2023rewrite`). Rewrites the query
before retrieval, optionally with a small RL-trained rewriter; consistent gains on open-domain and
multiple-choice QA. *For CR:* a blocked repeat should be rewritten, not dropped: the ledger returns the
block plus the list of allowed new keys.

**Query2doc** (Wang, Yang and Wei, EMNLP 2023, arXiv:2303.07678, `wang2023query2doc`). Expands a query with a
model-written pseudo-document, improving BM25 by 3% to 15% on MS MARCO and TREC DL. *For CR:* for FTS over
OCR text, expand with the phrasing a period source would use ("enlisted at", "Co. B", "relict of",
"departed this life"), never with invented facts.

**HyDE** (Gao et al., arXiv:2212.10496, `gao2022hyde`). Retrieves using the embedding of a hypothetical
answer document. *For CR:* useful only where there is a dense index; archive.org FTS is lexical, so prefer
Query2doc-style lexical expansion.

**FLARE** (Jiang et al., EMNLP 2023, arXiv:2305.06983, `jiang2023flare`). Decides when and what to retrieve
by checking low-confidence upcoming content. *For CR:* trigger a retrieval only for dossier sections still
marked missing or low confidence, which is what the outline plus value score does.

**Tabu Search** (Glover and Laguna, Springer 1997, `glover1997tabu`). Keeps a tabu list of recent moves
that may not be repeated unless an aspiration criterion overrides it. *For CR:* the search ledger is a
tabu list over canonical queries; the "new key" rule is the aspiration criterion, and the logged reason
makes each override auditable.

**Data Matching** (Christen, Springer 2012, `christen2012datamatching`) with Fellegi-Sunter
(`fellegi1969linkage`, already cited). Blocking, phonetic encodings and string similarity for names.
*For CR:* generate spelling variants (phonetic keys, initials, common transcription errors such as
St. John / Saint John / StJohn / Sinjin) as legitimate new keys, and canonicalize queries with the same
normalizer so trivial variants (case, punctuation, word order) count as repeats.

## 5. Exploration and foraging

**Go-Explore** (Ecoffet et al., Nature 590:580-586, 2021, `ecoffet2021goexplore`). Remembers visited
states, first returns to a promising one, then explores from it; it solved hard-exploration Atari games
where intrinsic-motivation methods failed. *For CR:* this is "repeat itself more cleverly": go back to a
source that paid off (a book with a hit) on purpose, with a new key (adjacent pages, a relative's name),
instead of re-running the same search from a different branch.

**Information Foraging** (Pirolli and Card, Psychological Review 106(4):643-675, 1999,
`pirolli1999foraging`). Searchers follow information scent and leave a patch when its gain rate drops
below the expected rate elsewhere. *For CR:* each source or collection is a patch; the allocator moves
budget away from a patch after k consecutive empty calls (B3 was empty 75.6% of the time and kept going).

**Curiosity and novelty** (Pathak et al. 2017; Schmidhuber 2010; Lehman and Stanley 2011, already cited).
*For CR:* keep the novelty bonus, but measure novelty over the ledger (new source, new page range, new
key) rather than over question text.

## The five findings that matter most for v0.2

1. **Budget, not cleverness, explains most variance** (Anthropic: 80% of BrowseComp variance from token
   usage). CR v0.1.0 used about 17 to 23 of 100 calls. v0.2 must spend its budget on new calls, and every
   comparison must be budget-matched.
2. **Repeats should become re-queries with a new key** (tabu search, Go-Explore, query rewriting). A ledger
   that blocks exact repeats and only allows revisits with a logged new key turns 41.4% waste into
   targeted returns to sources that paid off.
3. **Split by lane and plan the outline first** (Anthropic orchestrator, STORM, Co-STORM). Parallel workers
   help only with explicit, non-overlapping lanes and a shared view of what is covered.
4. **Rank leads with a value score and a bandit** (LATS, ToT, UCT, foraging). Expand the best lead first,
   back up real yield, and stop feeding a patch that keeps returning nothing.
5. **Keep verification as a hard gate** (MAST, debate, self-consistency). Multi-agent gains are often small
   and failures cluster in verification; CR's 66.9% precision is its one clear win and must not regress.
