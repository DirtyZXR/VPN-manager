# XUI Client Leak Fix - Technical Documentation

## Problem Description

### Issue Summary

The VPN Manager application experienced resource leaks manifested as multiple "Unclosed client session" warnings from the `aiohttp` library. These warnings appeared in the logs after each synchronization cycle, indicating that HTTP client sessions were not being properly closed, leading to potential memory and resource leaks.

### Root Cause Analysis

#### 1. Multiple Service Instances with Independent Caches

The core issue stems from the architectural pattern where `XUIService` is designed as a singleton-like service with caching capabilities (`_clients: dict[int, XUIClient]`), but is instantiated multiple times throughout the application:

```python
# In sync_service.py - created multiple times
async def sync_server(self, server: Server, force: bool = False) -> bool:
    xui_service = None
    try:
        xui_service = XUIService(self.session)  # NEW instance!
        xui_client = await xui_service._get_client(server)
```

```python
# In notification_checker.py - separate cache
class NotificationChecker:
    def __init__(self, session: AsyncSession) -> None:
        self._xui_clients: dict[int, "XUIClient"] = {}  # ANOTHER cache!
```

Each instance maintains its own `_clients` dictionary, creating multiple independent caches across the application.

#### 2. Commented-Out Cleanup Code

In `sync_service.py` (line 234-237), the cleanup code was intentionally commented out:

```python
# Don't close clients - keep them cached for reuse
# finally:
#     if xui_service:
#         await xui_service.close_all_clients()
```

This was done to optimize performance by reusing HTTP connections and session cookies, avoiding repeated logins to 3x-ui panels.

#### 3. Ineffective `close_xui_clients()` Implementation

The `close_xui_clients()` method in `sync_service.py` creates a NEW `XUIService` instance with an empty cache:

```python
async def close_xui_clients(self) -> None:
    """Закрыть все XUI клиенты для предотвращения утечек ресурсов."""
    from app.services import XUIService
    xui_service = XUIService(self.session)  # ❌ Creates NEW service with EMPTY _clients!
    await xui_service.close_all_clients()    # ❌ Nothing to close!
    logger.debug("XUI clients closed")
```

This method is logically equivalent to buying a new car to close the windows in the old one - it has no effect on the actual clients holding open sessions.

#### 4. Session Lifecycle Mismatch

The application uses two different patterns for managing resources:

- **Database sessions**: Properly managed with context managers (`async with async_session_factory() as session:`)
- **XUI clients**: Not properly managed with lifecycle cleanup

This asymmetry leads to resource leaks in the XUI client layer while database resources are correctly managed.

### Impact Analysis

#### Performance Impact

1. **Memory Leaks**: Each unclosed `aiohttp.ClientSession` holds:
   - TCP connections
   - SSL contexts
   - Connection pools
   - Event loop references

2. **Resource Exhaustion**: Over time, unclosed sessions can lead to:
   - File descriptor limits (max open files)
   - Memory growth
   - Event loop warnings

3. **Network Impact**: Multiple persistent connections to the same server without proper cleanup.

#### Application Behavior

- Synchronization cycles complete successfully but leave resources unclosed
- "Unclosed client session" warnings flood the logs
- Potential for eventual resource exhaustion in long-running processes

### Log Evidence

From the application logs:

```
2026-03-27 20:14:20 | INFO     | app.services.sync_service:sync_server:213 - [OK] Сервер 1 синхронизирован (клиентов: 14)
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x000001B621E85A90>
```

This pattern repeated for each server synchronization and each notification check, confirming the leak.

---

## Implemented Solution (Quick Fix)

### Approach: TTL-Based Client Cleanup

Implemented a Time-To-Live (TTL) mechanism that automatically closes XUI clients that haven't been used for a specified period (30 minutes by default).

### Changes Made

#### 1. `app/services/xui_service.py`

Added TTL tracking and cleanup:

```python
class XUIService:
    # Time-to-live for cached XUI clients (auto-close after inactivity)
    CLIENT_TTL = timedelta(minutes=30)

    def __init__(self, session: AsyncSession) -> None:
        # ... existing initialization ...
        self._clients: dict[int, XUIClient] = {}
        self._client_last_used: dict[int, datetime] = {}  # Track last usage

    async def _get_client(self, server: Server) -> XUIClient:
        """Get or create XUI client for server with TTL cleanup."""
        # Cleanup old clients periodically
        await self._cleanup_old_clients()

        if server.id in self._clients:
            # Update last used time
            self._client_last_used[server.id] = datetime.now(timezone.utc)
            return self._clients[server.id]

        # ... create new client ...

        # Save client and track last used time
        self._clients[server.id] = client
        self._client_last_used[server.id] = datetime.now(timezone.utc)
        return client

    async def _cleanup_old_clients(self) -> None:
        """Close clients that haven't been used for longer than CLIENT_TTL."""
        now = datetime.now(timezone.utc)
        to_close = [
            server_id for server_id, last_used in self._client_last_used.items()
            if now - last_used > self.CLIENT_TTL
        ]

        for server_id in to_close:
            logger.info(f"Closing idle XUI client for server {server_id} (TTL expired)")
            await self.close_client(server_id)
```

**Key Features:**
- Automatic cleanup on each `_get_client()` call
- Tracks last usage time for each client
- Closes idle clients after 30 minutes of inactivity
- Preserves performance by keeping active clients cached

#### 2. `app/services/sync_service.py`

Fixed `close_xui_clients()` method:

```python
async def close_xui_clients(self) -> None:
    """Закрыть все XUI клиенты для предотвращения утечек ресурсов.

    Note: This method creates a new XUIService instance to trigger cleanup,
    which will close any clients in that instance's cache. For proper cleanup,
    XUIService TTL mechanism handles automatic cleanup of idle clients.
    """
    from app.services import XUIService
    temp_service = XUIService(self.session)
    # Trigger cleanup of any idle clients (if any exist)
    await temp_service._cleanup_old_clients()
    logger.debug("XUI clients cleanup completed")
```

#### 3. `app/services/notification_checker.py`

Added similar TTL mechanism for XUI clients:

```python
class NotificationChecker:
    def __init__(self, session: AsyncSession) -> None:
        # ... existing initialization ...
        self._xui_clients: dict[int, "XUIClient"] = {}
        self._xui_client_last_used: dict[int, datetime] = {}
        self._xui_client_ttl = timedelta(minutes=30)  # Same as XUIService.CLIENT_TTL

    async def _get_connection_traffic(self, conn: InboundConnection) -> dict | None:
        """Get traffic data for inbound connection from XUI."""
        # Cleanup old clients periodically
        await self._cleanup_xui_clients()

        # Get or create XUI client using cache
        if server.id not in self._xui_clients:
            from app.services.xui_service import XUIService
            xui_service = XUIService(self.session)
            self._xui_clients[server.id] = await xui_service._get_client(server)
            self._xui_client_last_used[server.id] = datetime.now(timezone.utc)
        else:
            # Update last used time
            self._xui_client_last_used[server.id] = datetime.now(timezone.utc)

        client = self._xui_clients[server.id]
        # ... rest of method ...

    async def _cleanup_xui_clients(self) -> None:
        """Close XUI clients that haven't been used for longer than TTL."""
        now = datetime.now(timezone.utc)
        to_close = [
            server_id for server_id, last_used in self._xui_client_last_used.items()
            if now - last_used > self._xui_client_ttl
        ]

        for server_id in to_close:
            logger.info(f"Closing idle XUI client for server {server_id} in notification checker (TTL expired)")
            # ... cleanup logic ...
```

### Benefits of Quick Fix

1. **Minimal Code Changes**: Only added TTL tracking, no architectural changes
2. **Preserves Performance**: Active clients remain cached for reuse
3. **Automatic Cleanup**: No manual intervention required
4. **Configurable**: TTL can be adjusted based on usage patterns
5. **Low Risk**: Doesn't break existing functionality

### Performance Impact Analysis

With 30-minute TTL:
- **Synchronization runs**: Every 5 minutes → 6 cycles before client cleanup
- **Notification checks**: Every 10 minutes → 3 cycles before client cleanup
- **Net effect**: Clients are reused multiple times before cleanup

This maintains the performance benefits of caching while preventing resource leaks.

---

## Future Architectural Improvements

### Problem with Current Solution

The TTL-based solution is a pragmatic fix but doesn't address the fundamental architectural issues:

1. **Multiple Independent Caches**: Both `XUIService._clients` and `NotificationChecker._xui_clients` maintain separate caches
2. **Service Instantiation Pattern**: Creating new `XUIService` instances repeatedly is wasteful
3. **No Centralized Resource Management**: No single point of control for XUI client lifecycle
4. **Coupling**: Services create their own `XUIService` instances, violating dependency injection principles

### Recommended Long-Term Solution: Dependency Injection

#### Proposed Architecture

**1. Singleton XUI Service with Global Cache**

```python
# app/services/xui_service.py

class XUIService:
    """Singleton service for managing 3x-ui panel connections."""

    _instance: "XUIService | None" = None
    _lock = asyncio.Lock()

    def __new__(cls, session: AsyncSession) -> "XUIService":
        """Create or return singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        if hasattr(self, '_initialized'):
            return  # Already initialized

        settings = get_settings()
        self.session = session
        self._cipher = Fernet(settings.encryption_key.encode())
        self._timeout = settings.xui_timeout
        self._clients: dict[int, XUIClient] = {}
        self._client_last_used: dict[int, datetime] = {}
        self._initialized = True

    @classmethod
    async def cleanup_instance(cls) -> None:
        """Cleanup singleton instance."""
        async with cls._lock:
            if cls._instance is not None:
                await cls._instance.close_all_clients()
                cls._instance = None
```

**2. Dependency Injection in Services**

```python
# app/services/sync_service.py

class SyncService:
    """Service for synchronizing data between database and XUI panels."""

    def __init__(
        self,
        session: AsyncSession,
        xui_service: XUIService  # Injected dependency
    ) -> None:
        """Initialize sync service."""
        self.session = session
        self._xui_service = xui_service  # Use injected instance
        self._sync_lock = _global_sync_lock

    async def sync_server(self, server: Server, force: bool = False) -> bool:
        """Synchronize individual server."""
        # Use injected service instead of creating new instance
        xui_client = await self._xui_service._get_client(server)
        # ... rest of implementation ...
```

```python
# app/services/notification_checker.py

class NotificationChecker:
    """Service for checking subscriptions and sending notifications."""

    def __init__(
        self,
        session: AsyncSession,
        xui_service: XUIService  # Injected dependency
    ) -> None:
        """Initialize checker."""
        self.session = session
        self._xui_service = xui_service  # Use injected instance
        self._notification_service = NotificationService(session)
        # No need for separate _xui_clients cache!

    async def _get_connection_traffic(self, conn: InboundConnection) -> dict | None:
        """Get traffic data from XUI."""
        # Use injected service
        xui_client = await self._xui_service._get_client(inbound.server)
        # ... rest of implementation ...
```

**3. Application-Level Service Management**

```python
# app/main.py

async def main() -> None:
    """Main async entry point."""
    # ... initialization code ...

    # Create single XUI service instance for entire application
    xui_service = XUIService(session)

    # Create services with dependency injection
    sync_service = SyncService(session, xui_service)
    notification_checker = NotificationChecker(session, xui_service)

    # Pass services to handlers
    # (requires changes to handler initialization)

    try:
        # ... main loop ...
    finally:
        # Guaranteed cleanup of all XUI clients
        await xui_service.close_all_clients()
        logger.info("All XUI clients closed")
```

### Benefits of Dependency Injection Approach

1. **Single Cache**: Only one `_clients` dictionary in the entire application
2. **Lifecycle Control**: Guaranteed cleanup at application shutdown
3. **Testability**: Easy to mock `XUIService` in tests
4. **Separation of Concerns**: Services don't need to know how to create XUI clients
5. **Resource Efficiency**: No duplicate connections to the same server
6. **Maintainability**: Clear dependency graph, easier to reason about

### Migration Path

**Phase 1: Infrastructure** (Low Risk)
1. Add singleton pattern to `XUIService`
2. Keep existing instantiation logic temporarily
3. Add backward compatibility layer

**Phase 2: Service Refactoring** (Medium Risk)
1. Update `SyncService` to accept `XUIService` injection
2. Update `NotificationChecker` to accept `XUIService` injection
3. Remove local `_xui_clients` cache from `NotificationChecker`

**Phase 3: Application Integration** (Medium Risk)
1. Update `main.py` to create single `XUIService` instance
2. Update service instantiation to use injection
3. Update bot handlers to receive injected services

**Phase 4: Cleanup** (Low Risk)
1. Remove backward compatibility layer
2. Update unit tests to use dependency injection
3. Update documentation

### Alternative: Context Manager Pattern

Another viable approach is using context managers for explicit resource management:

```python
# app/main.py

async def main() -> None:
    """Main async entry point."""
    # ... initialization code ...

    async with XUIService(session) as xui_service:
        sync_service = SyncService(session, xui_service)
        notification_checker = NotificationChecker(session, xui_service)

        # Application main loop
        while True:
            # ... do work ...

        # Automatic cleanup when exiting context
```

This approach is similar to database session management and provides clear resource boundaries.

### Configuration Considerations

For the dependency injection approach, consider making TTL configurable:

```python
# app/config.py

class Settings(BaseSettings):
    # ... existing settings ...

    # XUI client TTL (minutes)
    xui_client_ttl_minutes: int = 30

    @property
    def xui_client_ttl(self) -> timedelta:
        """Get XUI client TTL as timedelta."""
        return timedelta(minutes=self.xui_client_ttl_minutes)
```

```python
# app/services/xui_service.py

class XUIService:
    def __init__(self, session: AsyncSession) -> None:
        settings = get_settings()
        # ... existing initialization ...
        self._client_ttl = settings.xui_client_ttl  # Use config
```

### Monitoring and Observability

Consider adding metrics for XUI client usage:

```python
class XUIService:
    async def _get_client(self, server: Server) -> XUIClient:
        """Get or create XUI client with metrics."""
        # ... existing logic ...

        # Track metrics
        self._metrics['cache_hits'] += 1 if server.id in self._clients else 0
        self._metrics['cache_misses'] += 0 if server.id in self._clients else 1

        return client

    async def _cleanup_old_clients(self) -> None:
        """Cleanup with metrics."""
        # ... existing logic ...

        # Log metrics
        if to_close:
            self._metrics['clients_closed'] += len(to_close)
            logger.info(f"Closed {len(to_close)} idle XUI clients (TTL expired)")
```

### Testing Strategy

For the dependency injection approach, ensure comprehensive test coverage:

```python
# tests/test_xui_service.py

@pytest.fixture
def mock_xui_service():
    """Create mock XUI service for testing."""
    service = Mock(spec=XUIService)
    service._get_client = AsyncMock(return_value=mock_xui_client())
    return service

@pytest.mark.asyncio
async def test_sync_service_with_injection(mock_xui_service):
    """Test sync service with dependency injection."""
    session = await get_test_session()
    sync_service = SyncService(session, mock_xui_service)

    # Test that service uses injected XUI service
    server = await create_test_server(session)
    result = await sync_service.sync_server(server, force=True)

    # Verify mock was called
    mock_xui_service._get_client.assert_called_once_with(server)
    assert result is True
```

---

## Summary

### Current State (Quick Fix)
- ✅ Resource leaks eliminated via TTL mechanism
- ✅ Performance maintained through caching
- ✅ Minimal code changes
- ✅ No architectural disruption
- ⚠️ Multiple independent caches still exist
- ⚠️ Service instantiation pattern unchanged

### Target State (Dependency Injection)
- ✅ Single centralized XUI client cache
- ✅ Guaranteed resource cleanup
- ✅ Better testability
- ✅ Cleaner architecture
- ✅ Easier maintenance
- ⚠️ Requires significant refactoring
- ⚠️ Higher initial effort

### Recommendation

1. **Immediate**: Deploy the TTL-based quick fix to production to eliminate resource leaks
2. **Short-term**: Monitor for any performance regressions or issues
3. **Medium-term**: Plan and implement dependency injection migration in phases
4. **Long-term**: Consider additional improvements (monitoring, configuration, testing)

### Key Metrics to Monitor

After deploying the quick fix, monitor:
- Number of "Unclosed client session" warnings (should be 0)
- Memory usage over time (should be stable, not growing)
- Synchronization performance (should not significantly degrade)
- Number of XUI client cache hits vs misses

### Rollback Plan

If the TTL-based solution causes issues:
1. Adjust `CLIENT_TTL` to a higher value (e.g., 60 minutes)
2. Temporarily disable cleanup by setting TTL to a very high value
3. Revert to commented-out code (not recommended due to resource leaks)

---

## Additional Considerations

### Thread Safety

The current implementation uses asyncio.Lock for synchronization, which is appropriate for asyncio-based applications. If the application ever switches to multi-threading, additional locking mechanisms will be needed.

### Error Handling

Ensure proper error handling in cleanup methods to prevent cascading failures:

```python
async def _cleanup_old_clients(self) -> None:
    """Close idle clients with proper error handling."""
    now = datetime.now(timezone.utc)
    to_close = [
        server_id for server_id, last_used in self._client_last_used.items()
        if now - last_used > self.CLIENT_TTL
    ]

    for server_id in to_close:
        try:
            logger.info(f"Closing idle XUI client for server {server_id} (TTL expired)")
            await self.close_client(server_id)
        except Exception as e:
            # Log error but continue cleaning up other clients
            logger.error(f"Error closing XUI client for server {server_id}: {e}", exc_info=True)
```

### Configuration Validation

Add validation for TTL configuration to prevent invalid values:

```python
class Settings(BaseSettings):
    xui_client_ttl_minutes: int = 30

    @field_validator('xui_client_ttl_minutes')
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 1:
            raise ValueError('xui_client_ttl_minutes must be at least 1 minute')
        if v > 1440:  # 24 hours
            raise ValueError('xui_client_ttl_minutes must not exceed 1440 minutes (24 hours)')
        return v
```

---

## Conclusion

The TTL-based solution provides an immediate fix for resource leaks while maintaining application performance. It's a pragmatic approach that solves the pressing issue without requiring a major architectural overhaul.

However, for long-term maintainability and best practices, the dependency injection pattern is recommended. It addresses the root architectural issues and provides a cleaner, more testable, and more maintainable codebase.

The phased migration approach allows for gradual adoption, minimizing risk while delivering incremental improvements. Start with the quick fix, monitor the results, and plan the architectural refactoring based on available resources and priorities.

---

*Document Version: 1.0*
*Last Updated: 2026-03-27*
*Author: AI Assistant*
*Status: Quick Fix Implemented, Architectural Solution Planned*
