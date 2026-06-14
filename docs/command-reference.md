## Command Reference

```
/trinity <provider>[:<instance>] "task"          # single dispatch
/trinity <p1>[:<i>] "t1" <p2> "t2"              # multi-provider parallel
/trinity <provider>*N "task"                     # N parallel same-provider
/trinity <preset> "task"                         # dispatch to a preset's provider set
/trinity plan <p1> "t1" <p2> "t2"               # plan with diagram, confirm, execute
/trinity plan "high-level description"           # auto-decompose, confirm, execute
/trinity install <provider>                      # install + register provider
/trinity status                                  # registered providers + presets + sessions
/trinity heartbeat [<instance>]                  # on-demand liveness check
/trinity clear [<instance> | all]                # clear sessions
/trinity help                                    # show this README
```

Reserved subcommands (cannot be used as provider, preset, or alias names):
`status`, `clear`, `plan`, `heartbeat`, `install`, `help`.

Built-in presets (when configured): `review`, `fast-review`, `deep-review`,
with aliases `r`, `fr`, `dr`. See [Review presets](usage-guide.md#review-presets).
