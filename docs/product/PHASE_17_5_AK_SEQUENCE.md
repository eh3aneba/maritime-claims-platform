# Phase 17.5-AK Sequence

```mermaid
sequenceDiagram
    participant P as Provider
    participant A as Read-only adapter
    participant S as MCRI control plane
    participant H as Human admin
    participant D as Canonical Evidence
    participant Z as Phase-Z processing release

    S->>A: governed profile + credential reference
    A->>P: transient OAuth + bounded metadata read
    P-->>A: metadata/version
    A-->>S: non-secret projection
    S->>S: due observation
    alt unchanged
        S-->>H: unchanged status
    else changed
        S-->>H: AG review handoff
        H->>S: explicit approve_refresh
        S->>A: exact changed-item read
        A->>P: exact metadata + read-only content GET
        P-->>A: current version + bytes
        A-->>S: bounded version proof + transient bytes
        S->>S: quarantine staging
        H->>S: separate AH admission authorization
        H->>S: separate AJ execution
        S->>D: create N+1; preserve N historical
        S-->>H: Phase-Z still required
        H->>Z: separate release for exact N+1
    else missing
        S-->>H: review-only missing handoff
        Note over S,D: no automatic canonical delete
    end
```

The diagram intentionally shows independent human boundaries. The operator page may present them together, but the APIs do not collapse them into a single action.
