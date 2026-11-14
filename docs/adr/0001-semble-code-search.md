# ADR 0001: semble for code search (plan 8.7, retrieval slot 2)

**Status: not adopted.** Decided 2026-11-12 by measurement at `f65d835` (`main` at the time). The [questions](data/0001-questions.json), the [plans](data/0001-plans.json) and the decision rule were committed in `78dedd5` before either method ran; [harness](data/0001_measure.py), [results](data/0001-results.json). Added on 2026-11-13, after a check across the ADRs and with the results unchanged: the ripgrep-alone row, the [always-on counts](data/0001-always-on.json) and their [counter](data/0001_count_tokens.py), and which agents the default install would configure on this machine.

## Candidate

[MinishLab/semble](https://github.com/MinishLab/semble) **0.7.2**: tag commit `bb746c9`, on PyPI 2026-11-03 (0.7.3, of 2026-11-08, is inside the 7-day wait). MIT. Maintainers Thomas van Dongen and Stéphan Tulkens (MinishLab). Read 2026-11-12. It ranks tree-sitter chunks by BM25 plus static embeddings from [`minishlab/potion-code-16M-v2`](https://huggingface.co/minishlab/potion-code-16M-v2) (MIT, revision `e9d2a44`), on CPU.

## Decision

Not adopted. The rule compares semble with slot 1 as fixed before the run: within the top 3 semble answers 21 questions against 24, 3 fewer where 5 more were required, and within the top 1 and the top 5 it answers 16 against 19 and 23 against 26, 3 fewer each where no fewer were required (without Q25's helper: 3, 4 and 4 fewer at top 1, 3 and 5). Against ripgrep alone (20, 25 and 26) it answers 4, 4 and 3 fewer (4, 5 and 4 without the helper), so the rule fails on all three counts whichever baseline is taken. Even against slot 1 in ripgrep's printed order (pyright's lookup still first) its lead at top 3 is 2 (1 without the helper), and against ripgrep alone in that order it is 1 (0). As a CLI it would cost about 60 times slot 1's time per question and 3.7 times its printed text; with the default install (MCP), which this machine's policy does not allow as it stands, it would cost about 1,600 tokens in every Claude Code session, with searches at 0.9 ms in process. Either way it keeps a second copy of the code in `~/.cache`. Slot 3 (a context store) is therefore measured against slot 1. Look at semble again only if a question set on a larger repo shows slot 1 failing.

Full record: [data/0001-record.md](data/0001-record.md)
