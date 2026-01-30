# User Cost Dashboard Plan

## Overview

Provide users with visibility into the processing costs associated with their podcast subscriptions. This helps users understand their resource usage and enables fair cost attribution for potential future billing tiers.

## Cost Model

### Current Pricing (Groq)

| Service | Rate | Notes |
|---------|------|-------|
| Whisper Large v3 Turbo | $0.04/hour | Dominant cost |
| LLM (ad classification) | ~$0.001/episode | Negligible |
| Railway compute | Shared | Not attributed to users |

### Cost Attribution

Each processed episode's cost is attributed to **all users subscribed to that feed** at processing time, split equally:

```
episode_cost = episode_duration_hours × $0.04
user_cost = episode_cost / subscribers_count
```

**Example**: A 1-hour episode from a feed with 2 subscribers:
- Episode cost: $0.04
- Cost per user: $0.02

## Data Requirements

### Prerequisites

This plan depends on **Data Retention Improvement** being implemented first to preserve:
- `ModelCall` records (or aggregated summaries)
- `post.duration` values
- Feed subscription history

### New Data Needed

#### 1. Cost Aggregation Tables

These summary tables allow cost tracking even if raw `ModelCall` records are eventually purged:

**`DailyCostSummary`**: System-wide daily cost aggregates

```python
class DailyCostSummary(db.Model):
    __tablename__ = "daily_cost_summary"
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    
    # Whisper costs
    whisper_calls = db.Column(db.Integer, default=0)
    whisper_audio_seconds = db.Column(db.Integer, default=0)
    whisper_cost_usd = db.Column(db.Float, default=0.0)
    
    # LLM costs (for future use)
    llm_calls = db.Column(db.Integer, default=0)
    llm_input_tokens = db.Column(db.Integer, default=0)
    llm_output_tokens = db.Column(db.Integer, default=0)
    llm_cost_usd = db.Column(db.Float, default=0.0)
    
    # Processing stats
    posts_processed = db.Column(db.Integer, default=0)
    posts_failed = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Aggregation Job**: Scheduled daily to populate cost summaries

```python
@scheduler.task("cron", id="aggregate_daily_costs", hour=1, minute=0)
def aggregate_daily_costs():
    """Run at 1 AM to aggregate previous day's costs."""
    yesterday = date.today() - timedelta(days=1)
    
    # Aggregate whisper costs
    whisper_stats = db.session.query(
        func.count(ModelCall.id),
        func.sum(Post.duration)
    ).join(Post).filter(
        func.date(ModelCall.timestamp) == yesterday,
        ModelCall.model_name.like('%whisper%')
    ).first()
    
    summary = DailyCostSummary(
        date=yesterday,
        whisper_calls=whisper_stats[0] or 0,
        whisper_audio_seconds=whisper_stats[1] or 0,
        whisper_cost_usd=(whisper_stats[1] or 0) / 3600 * 0.04
    )
    db.session.merge(summary)
    db.session.commit()
```

#### 2. Processing Attribution Table

Track which users were subscribed when an episode was processed:

```python
class ProcessingAttribution(db.Model):
    __tablename__ = "processing_attribution"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False)
    
    # Snapshot at processing time
    subscribers_at_processing = db.Column(db.Integer, nullable=False)
    episode_duration_seconds = db.Column(db.Integer, nullable=False)
    
    # Calculated costs
    whisper_cost_share_usd = db.Column(db.Float, nullable=False)
    
    processed_at = db.Column(db.DateTime, nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint("post_id", "user_id", name="uq_post_user"),
        db.Index("ix_attribution_user_month", "user_id", "processed_at"),
    )
```

#### 2. Monthly User Summary (from data retention plan)

```python
class UserCostSummary(db.Model):
    __tablename__ = "user_cost_summary"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # "2026-01"
    
    whisper_audio_seconds = db.Column(db.Integer, default=0)
    whisper_cost_usd = db.Column(db.Float, default=0.0)
    posts_processed = db.Column(db.Integer, default=0)
    
    # Per-feed breakdown stored as JSON
    feed_breakdown = db.Column(db.JSON, default=dict)
    # Example: {"feed_id_1": {"posts": 5, "cost": 0.50}, ...}
```

## API Endpoints

### User Cost Summary

```
GET /api/user/costs
GET /api/user/costs?month=2026-01
```

**Response**:
```json
{
  "current_month": {
    "month": "2026-01",
    "total_cost_usd": 1.57,
    "total_hours": 39.25,
    "episodes_processed": 42,
    "feeds": [
      {
        "feed_id": 20,
        "feed_title": "ok storytime",
        "episodes": 11,
        "hours": 12.5,
        "cost_usd": 0.50
      },
      {
        "feed_id": 11,
        "feed_title": "Stuff They Don't Want You To Know",
        "episodes": 8,
        "hours": 9.2,
        "cost_usd": 0.37
      }
    ]
  },
  "historical": [
    {"month": "2025-12", "total_cost_usd": 0.85, "episodes": 22}
  ]
}
```

### Feed Cost Estimate

Allow users to preview cost before subscribing:

```
GET /api/feed/{feed_id}/cost-estimate
```

**Response**:
```json
{
  "feed_id": 20,
  "feed_title": "ok storytime",
  "estimate": {
    "avg_episode_duration_hours": 1.2,
    "episodes_per_month": 8,
    "current_subscribers": 2,
    "estimated_monthly_cost_usd": 0.19,
    "note": "Cost is split among all subscribers"
  }
}
```

## Frontend Components

### 1. Cost Dashboard Page

Location: `/settings/costs` or `/dashboard/costs`

```
┌─────────────────────────────────────────────────────┐
│  Your Processing Costs                              │
├─────────────────────────────────────────────────────┤
│                                                     │
│  January 2026                                       │
│  ┌───────────────────────────────────────────────┐  │
│  │  Total: $1.57          39.25 hours processed  │  │
│  │  ████████████████░░░░  42 episodes            │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  By Feed                                            │
│  ┌───────────────────────────────────────────────┐  │
│  │ ok storytime              $0.50  (11 eps)     │  │
│  │ ████████████                                  │  │
│  │ Stuff They Don't...       $0.37  (8 eps)      │  │
│  │ █████████                                     │  │
│  │ The Indicator             $0.25  (6 eps)      │  │
│  │ ██████                                        │  │
│  │ [5 more feeds...]                             │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Historical                                         │
│  ┌───────────────────────────────────────────────┐  │
│  │ Dec 2025: $0.85 (22 episodes)                 │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 2. Feed Subscription Cost Preview

Show estimated cost when subscribing to a new feed:

```
┌─────────────────────────────────────────────────────┐
│  Subscribe to "The Daily"                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│  📊 Estimated Monthly Cost                          │
│                                                     │
│  ~$0.35/month                                       │
│  Based on: 22 episodes/month × 0.4 hrs avg          │
│  Cost shared with 3 other subscribers               │
│                                                     │
│  [Subscribe]  [Cancel]                              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 3. Settings Integration

Add cost summary to user settings page:

```
┌─────────────────────────────────────────────────────┐
│  Account Settings                                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Subscriptions: 5 feeds                             │
│  This Month: $1.57 processing costs                 │
│  [View detailed costs →]                            │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Backend Foundation

- [ ] Implement data retention improvements (prerequisite)
- [ ] Add `ProcessingAttribution` model
- [ ] Create migration (request from user)
- [ ] Update `processor.py` to record attribution on processing
- [ ] Add aggregation job to compute `UserCostSummary`

### Phase 2: API Endpoints

- [ ] Create `/api/user/costs` endpoint
- [ ] Create `/api/feed/{id}/cost-estimate` endpoint
- [ ] Add authentication/authorization checks
- [ ] Add unit tests for cost calculations

### Phase 3: Frontend Dashboard

- [ ] Create `CostDashboard` component
- [ ] Create `FeedCostEstimate` component
- [ ] Add route to frontend router
- [ ] Integrate with settings page
- [ ] Add cost preview to feed subscription flow

### Phase 4: Polish

- [ ] Add loading states and error handling
- [ ] Add tooltips explaining cost model
- [ ] Add CSV export for cost history
- [ ] Mobile-responsive design

## Cost Calculation Logic

### On Episode Processing

```python
def record_processing_attribution(post: Post):
    """Record cost attribution when an episode is processed."""
    subscribers = FeedSupporter.query.filter_by(feed_id=post.feed_id).all()
    subscriber_count = len(subscribers)
    
    if subscriber_count == 0:
        return  # No attribution needed
    
    episode_cost = (post.duration / 3600) * 0.04  # Whisper cost
    cost_per_user = episode_cost / subscriber_count
    
    for supporter in subscribers:
        attribution = ProcessingAttribution(
            post_id=post.id,
            user_id=supporter.user_id,
            feed_id=post.feed_id,
            subscribers_at_processing=subscriber_count,
            episode_duration_seconds=post.duration,
            whisper_cost_share_usd=cost_per_user,
            processed_at=datetime.utcnow()
        )
        db.session.add(attribution)
```

### Monthly Aggregation

```python
def aggregate_user_costs_for_month(user_id: int, month: str):
    """Aggregate user costs for a given month."""
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date + timedelta(days=32)).replace(day=1)
    
    attributions = ProcessingAttribution.query.filter(
        ProcessingAttribution.user_id == user_id,
        ProcessingAttribution.processed_at >= start_date,
        ProcessingAttribution.processed_at < end_date
    ).all()
    
    total_cost = sum(a.whisper_cost_share_usd for a in attributions)
    total_seconds = sum(a.episode_duration_seconds / a.subscribers_at_processing 
                       for a in attributions)
    
    feed_breakdown = {}
    for a in attributions:
        if a.feed_id not in feed_breakdown:
            feed_breakdown[a.feed_id] = {"posts": 0, "cost": 0.0}
        feed_breakdown[a.feed_id]["posts"] += 1
        feed_breakdown[a.feed_id]["cost"] += a.whisper_cost_share_usd
    
    return UserCostSummary(
        user_id=user_id,
        month=month,
        whisper_audio_seconds=int(total_seconds),
        whisper_cost_usd=total_cost,
        posts_processed=len(attributions),
        feed_breakdown=feed_breakdown
    )
```

## Privacy Considerations

- Users can only see their own costs
- Aggregate subscriber counts are shown (not individual subscribers)
- Feed-level costs are visible to feed subscribers only
- Admin dashboard can see global costs (separate feature)

## Future Enhancements

1. **Cost alerts**: Notify users if monthly costs exceed threshold
2. **Budget limits**: Allow users to set processing limits
3. **Billing integration**: If moving to paid tiers, use this data for invoicing
4. **Cost optimization tips**: Suggest unsubscribing from high-cost, low-listen feeds
