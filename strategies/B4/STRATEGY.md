# B4: CR without durability

**What it is.** The same question loop as B5, run in a plain asyncio process with no durable
state. It exists only for H2 (durability under worker kills and flaky archives); it is not part
of the corpus-replication leaderboard.

**What it shows.** When the process dies, finished lookups are lost and redone on restart.

Code: `bench/baselines/cr_plain_loop.py`. Config: `config.json`. Preregistered.
