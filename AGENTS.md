# tvrec

A TV and film discovery engine for one household: it finds high-quality,
varied things to watch that stretch their taste, with long-tail titles as
welcome as popular ones. It builds one local database (the "soup") from public
data about titles, the people who made them and how the public rated them,
adds the household's own viewing and verdicts, and ranks titles for each
person.

## This repository is public; private data never enters it

Git holds code, schemas and documentation only. The household's data stays on
their own machines and never goes in a commit, a commit message, a test
fixture, a code comment, an example, or an issue: what they watched and when,
their verdicts and taste notes, their words, their names, and the addresses,
hostnames and tokens of their machines and accounts. One leaked commit is
public for good, because forks and caches keep it after a force-push.

- `data/` holds downloaded data sets and the built database. `private/` holds
  household data and local configuration. Both are ignored by git; keep it so.
- Code reads private values (server addresses, tokens, people) from
  `private/` or the environment at run time, never from a literal.
- Examples and tests use well-known titles and invented people.
- Before a commit, read `git diff --cached` for household data. If some has
  already been committed, stop and tell the owner before pushing anything.

The owner will say when this changes.

## Data sets

Each downloaded data set has its own licence, most of them for personal,
non-commercial use. Do not commit or redistribute the data itself; record
where each file came from and its licence in `docs/data-sources.md`.

## Engineering

Simple as possible but no simpler: one obvious way to do each thing, few
knobs, no speculative features. Tests follow a path a person would take;
prefer no test to a useless one.
