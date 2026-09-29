# Phase 17.6-AA — SFTP human review decisions

Phase AA lets an Admin reviewer make terminal human decisions on pending SFTP review handoffs.

## Allowed decisions

Changed:
- dismiss.

Missing:
- acknowledge_missing;
- dismiss.

## Still blocked

Changed → approve_refresh remains explicitly blocked for SFTP until Phase AB.

The block happens before decision persistence and before any refresh authorization can be created.

## Safety

Decision actions perform no:
- SFTP/provider I/O;
- object-storage I/O;
- Document or Claim mutation;
- checkpoint advancement;
- processing enqueue;
- AI execution.

## Compatibility

SharePoint and Google Drive keep their existing decision matrix, including approve_refresh.

## Next

Phase AB will separately widen SFTP refresh authorization and prove the controlled refresh path.
