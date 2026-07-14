# Diagrammes Machine à États


### États Candidature

```
                    ┌─────────────┐
                    │     NEW     │ ◄─── reset ────┐
                    └─────────────┘                │
                      │  │  │  │                   │
          ┌───────────┘  │  │  └─────────────┐    │
          │              │  │                 │    │
       process     add_to_pool        move_to_│    │
          │              │                  prior  │
          ↓              ↓                    │    │
    ┌──────────┐   ┌──────────┐              ↓    │
    │PROCESSING│   │   POOL   │        ┌──────────┴────┐
    └──────────┘   └──────────┘        │ PRIOR_TO_HIRE │
          │  │           │              └───────────────┘
      postpone│           │                     │
          │  │           │         cancel_prior_to_hire
          │  │           │                     │
          ↓  │           │                     ↓
    ┌──────────┐         │              (retour PROCESSING)
    │POSTPONED │         │
    └──────────┘         │
          │              │
          └──────┬───────┴────────┐
                 │                │
              accept           refuse
                 │                │
                 ↓                ↓
           ┌──────────┐     ┌──────────┐
           │ ACCEPTED │     │ REFUSED  │
           └──────────┘     └──────────┘
                 │
              cancel
                 │
                 ↓
           ┌──────────┐
           │CANCELLED │
           └──────────┘

    (render_obsolete) → OBSOLETE ──┐
                                    │
                                 reset
                                    │
                                    └────► (retour NEW)
```

### États Fiche Salarié

```
         ┌──────────────┐
    ┌────│     NEW      │◄────┐
    │    └──────────────┘     │
    │            │           enable
  ready          │             │
    │         ready            │
    │            ↓             │
    │    ┌──────────────┐     │
    └───►│    READY     │     │
         └──────────────┘     │
                 │             │
      wait_for_asp_response   │
                 │             │
                 ↓             │
         ┌──────────────┐     │
         │     SENT     │     │
         └──────────────┘     │
              │     │          │
        process│   │reject    │
              │     │          │
              ↓     ↓          │
       ┌──────────┐ ┌────────┐│
       │PROCESSED │ │REJECTED││
       └──────────┘ └────────┘│
              │         │      │
           disable   ready     │
              │         │      │
              ↓         └──────┘
       ┌──────────────┐
       │   DISABLED   │
       └──────────────┘
              │
           archive
              │
              ↓
       ┌──────────────┐
       │   ARCHIVED   │
       └──────────────┘
         │  │  │
unarchive│  │  │unarchive_rejected
    _new │  │  │
         │  │  │
         ↓  ↓  ↓
       NEW PROCESSED REJECTED
```

### États Agrément (Calculés)

```
    aujourd'hui < start_at
         ↓
    ┌─────────┐
    │ FUTURE  │
    └─────────┘

    start_at ≤ aujourd'hui ≤ end_at ET non suspendu
         ↓
    ┌─────────┐
    │  VALID  │
    └─────────┘

    start_at ≤ aujourd'hui ≤ end_at ET suspendu
         ↓
    ┌──────────┐
    │SUSPENDED │
    └──────────┘

    end_at < aujourd'hui
         ↓
    ┌─────────┐
    │ EXPIRED │
    └─────────┘
```


