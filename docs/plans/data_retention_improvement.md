# Data Retention Improvement Plan

## Problem Statement

The current cleanup job (`src/app/post_cleanup.py`) deletes **all processing metadata** when cleaning up old posts, not just the large audio files. This makes it impossible to:

1. Debug issues that occurred more than 5 days ago
2. Track processing patterns over time
3. Maintain historical records for analysis

## Current Behavior

When a post is cleaned up (after 5 days), `cleanup_processed_post_action` calls `clear_post_processing_data_action` which deletes:

| Data | Current Action | Storage Impact |
|------|----------------|----------------|
| `unprocessed_audio_path` file | Deleted | **High** (10-200MB each) |
| `processed_audio_path` file | Deleted | **High** (10-200MB each) |
| `ModelCall` records | **Deleted** | Low (~1KB each) |
| `ProcessingJob` records | **Deleted** | Low (~500B each) |
| `TranscriptSegment` records | **Deleted** | Medium (~10KB each) |
| `Identification` records | **Deleted** | Low (~200B each) |
| `post.duration` | **Set to NULL** | None |

## Proposed Changes

**Goal**: Retain processing metadata while still freeing disk space.

### 1. Create New Cleanup Action

Add to existing file `src/app/writer/actions/cleanup.py` (alongside `clear_post_processing_data_action` and `cleanup_processed_post_action`):

```python
def cleanup_processed_post_files_only_action(params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove audio files but preserve processing metadata."""
    post_id = params.get("post_id")
    post = db.session.get(Post, int(post_id))
    if not post:
        raise ValueError(f"Post {post_id} not found")
    
    logger.info("[WRITER] cleanup_processed_post_files_only_action: post_id=%s", post_id)
    
    # Delete audio files (using same pattern as post_cleanup.py)
    for path_str in [post.unprocessed_audio_path, post.processed_audio_path]:
        if not path_str:
            continue
        try:
            file_path = Path(path_str)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[WRITER] Invalid path for post %s: %s", post.guid, path_str
            )
            continue
        if not file_path.exists():
            continue
        try:
            file_path.unlink()
            logger.info("[WRITER] Deleted file: %s", file_path)
        except OSError as exc:
            logger.warning(
                "[WRITER] Unable to delete %s: %s", file_path, exc
            )
    
    # Clear file paths but preserve duration and other metadata
    post.unprocessed_audio_path = None
    post.processed_audio_path = None
    # Un-whitelist the post (prevents re-queuing for processing)
    post.whitelisted = False
    
    # DO NOT delete: ModelCall, ProcessingJob, TranscriptSegment, Identification
    # DO NOT null: post.duration
    
    logger.info(
        "[WRITER] cleanup_processed_post_files_only_action: completed post_id=%s",
        post_id,
    )
    
    return {"post_id": post.id}
```

### 2. Modify `post_cleanup.py`

Update `cleanup_processed_posts()` to use the new files-only action.

In `src/app/post_cleanup.py`, line ~100:

```python
writer_client.action(
    "cleanup_processed_post_files_only", 
    {"post_id": post.id}, 
    wait=True
)
```

### 3. Register Action in Executor

Add to `src/app/writer/executor.py` in `_register_default_actions()`:

```python
self.register_action(
    "cleanup_processed_post_files_only",
    writer_actions.cleanup_processed_post_files_only_action,
)
```

And add to `src/app/writer/actions/__init__.py`:

```python
from app.writer.actions.cleanup import (
    cleanup_processed_post_files_only_action as cleanup_processed_post_files_only_action,
    # ... other imports
)
```

### 4. Keep `clear_post_processing_data_action` 

Retain the existing full-clear action for manual use (e.g., user requests data deletion, GDPR compliance).

## Implementation Steps

### Step 1: Add Duration Validation (CRITICAL)
- [ ] Modify `src/podcast_processor/transcription_manager.py::_check_existing_transcription()`
- [ ] Add duration comparison before reusing cached transcription
- [ ] Import `get_audio_duration_ms` from `podcast_processor.audio`
- [ ] Log when duration mismatch detected
- [ ] Return `None` to trigger fresh transcription if duration changed

### Step 2: Create New Cleanup Action
- [ ] Add `cleanup_processed_post_files_only_action` to `src/app/writer/actions/cleanup.py`
- [ ] Register action in `src/app/writer/executor.py` (`_register_default_actions`)
- [ ] Export action in `src/app/writer/actions/__init__.py`

### Step 3: Update Cleanup Job
- [ ] Modify `src/app/post_cleanup.py` line ~100 to call new action
- [ ] Verify retention period configuration (`post_cleanup_retention_days`, default: 5 days)

### Step 4: Testing
- [ ] Unit tests for new cleanup action verifying:
  - Audio files are deleted
  - File paths are cleared
  - `post.whitelisted` is set to False
  - `post.duration` is preserved
  - Metadata records (ModelCall, ProcessingJob, etc.) are preserved
- [ ] **NEW: Test duration validation on reprocess**
  - Mock changed audio duration
  - Verify fresh transcription triggered
  - Verify correct processing with new timestamps
- [ ] Integration test with actual post cleanup job
- [ ] Verify disk space is freed
- [ ] Verify posts are not re-queued for processing after cleanup

## Notes

**`post.whitelisted` field**: Controls whether a post should be processed/served. Set to `True` when user requests processing, set to `False` during cleanup to prevent re-processing. Posts with `whitelisted=False` return HTTP 403 on download attempts (unless auto-whitelist is enabled).

**Retention period**: Configured via `post_cleanup_retention_days` (default: 5 days from `shared/defaults.py`). This plan does not change the retention period, only what data is deleted.

**Error handling**: File deletion failures are logged as warnings but don't block cleanup. Database paths are cleared even if file deletion fails (matching existing behavior in `post_cleanup.py`).

**Return value**: Writer actions return `{"post_id": post.id}` to maintain consistency with existing cleanup actions.

## Rollout Plan

1. **Deploy** - Switch to files-only cleanup, immediately stops metadata loss
2. **Monitor** - Verify disk space is freed and database size is stable
