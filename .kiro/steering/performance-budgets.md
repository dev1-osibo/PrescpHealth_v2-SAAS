---
inclusion: always
---

# Performance Budgets — PrescpHealth Rebuild

## Core Principle

Clinicians in Africa often work with limited bandwidth and older hardware. Performance is not a luxury — it directly impacts clinical workflow speed and patient outcomes. Every millisecond matters when a doctor is reviewing a critical alert.

## API Response Time Targets

| Operation Type | Target (p95) | Hard Limit | Action if Exceeded |
|---------------|-------------|------------|-------------------|
| Simple reads (GET patient, GET alerts) | <200ms | 500ms | Investigate query plan |
| List/search with pagination | <300ms | 800ms | Add index or cache |
| Writes (POST measurement, PUT patient) | <500ms | 1000ms | Check middleware overhead |
| Async task trigger (POST risk/compute) | <200ms | 500ms | Just enqueues, should be fast |
| ML computation (Celery task) | <5s | 30s | Optimize model or batch |
| Report generation (PDF) | <10s | 60s | Acceptable for async |
| Bulk import (100 rows) | <5s | 30s | Stream processing |

## Database Query Budgets

| Query Type | Target | Flag Threshold | Action |
|-----------|--------|---------------|--------|
| Single row by PK | <5ms | >20ms | Check connection pool |
| Indexed lookup | <20ms | >100ms | Review index usage |
| List with filters | <50ms | >200ms | Add composite index |
| Aggregation (population metrics) | <200ms | >1000ms | Use materialized view or cache |
| Full-text search | <100ms | >500ms | Check GIN index |
| Join across 2 tables | <50ms | >200ms | Verify join indexes |
| Join across 3+ tables | <100ms | >500ms | Consider denormalization |

## Frontend Performance Budgets

### Bundle Size
| Asset | Budget | Hard Limit |
|-------|--------|------------|
| Initial JS bundle (gzipped) | <150KB | 250KB |
| Initial CSS (gzipped) | <30KB | 50KB |
| Per-route chunk (lazy loaded) | <50KB | 100KB |
| Total app (all chunks) | <500KB | 1MB |

### Loading Performance
| Metric | Target | Hard Limit |
|--------|--------|------------|
| First Contentful Paint (FCP) | <1.5s | 3s |
| Largest Contentful Paint (LCP) | <2.5s | 4s |
| Time to Interactive (TTI) | <3s | 5s |
| Cumulative Layout Shift (CLS) | <0.1 | 0.25 |
| First Input Delay (FID) | <100ms | 300ms |

### Runtime Performance
- No UI jank: maintain 60fps during scrolling and animations
- Chart rendering: <500ms for datasets up to 1000 points
- Table rendering: <200ms for 100 rows with sorting
- Search/filter: <100ms response to user input (debounce at 300ms)

## Network Considerations (Africa-Specific)

- Design for 3G connections (1-2 Mbps) as baseline
- Implement progressive loading — show skeleton UI immediately, fill data as it arrives
- Cache aggressively on the client for non-PHI data (UI assets, translations, static config)
- API responses should be compact — no unnecessary fields, use pagination
- Consider offline-first for patient portal (service worker for basic read access)
- Image optimization: WebP format, lazy loading, responsive sizes

## Celery Task Performance

| Task Type | Target Duration | Max Duration | Queue Priority |
|-----------|----------------|-------------|----------------|
| Alert dispatch | <2s | 10s | Highest (notification) |
| Risk computation (single patient) | <5s | 30s | High (risk) |
| Forecast computation | <10s | 60s | Medium (forecast) |
| Report generation (PDF) | <15s | 120s | Low (report) |
| Population metrics refresh | <60s | 300s | Low (report) |
| Bulk import processing | <1s per row | 5s per row | Medium (forecast) |

## Redis Performance

- Cache hit ratio target: >90% for frequently accessed data
- Cache operation latency: <2ms (if exceeds, check network/connection pool)
- Rate limit check: <1ms
- Queue enqueue: <5ms

## Monitoring and Enforcement

- Log slow queries (>100ms) automatically with query plan
- Log slow API responses (>500ms) with correlation_id for investigation
- Frontend: Lighthouse CI in build pipeline, fail build if budgets exceeded
- Backend: middleware tracks and logs response times per endpoint
- Weekly performance review: identify top 10 slowest endpoints, optimize top 3

## Optimization Strategies (Use When Budgets Exceeded)

1. **Database**: Add indexes, use EXPLAIN ANALYZE, consider materialized views
2. **Caching**: Cache computed results (risk scores, population metrics) in Redis
3. **Pagination**: Never return unbounded result sets
4. **Lazy loading**: Frontend code-splits per route, images load on scroll
5. **Compression**: gzip/brotli on all API responses
6. **Connection pooling**: Tune pool size for concurrent load
7. **Query batching**: N+1 query detection and resolution with eager loading
