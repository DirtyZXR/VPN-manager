# Client Search Feature Implementation

## Summary
Implemented a comprehensive client search feature to replace the display of all clients, addressing the scalability issue when dealing with large numbers of clients.

## Changes Made

### 1. FSM States (`app/bot/states/admin.py`)
Added two new search states to `ClientManagement`:
- `waiting_for_search_query`: State for processing search input
- `waiting_for_search_field`: State for selecting search criteria

### 2. Client Service (`app/services/client_service.py`)
Added `search_clients()` method with support for:
- **Name search**: Partial case-insensitive matching
- **Email search**: Partial case-insensitive matching
- **Telegram ID search**: Exact matching
- **XUI email search**: Partial case-insensitive matching across inbound connections
- **Combined search**: Supports multiple criteria simultaneously

The method uses SQLAlchemy joins to search across related tables (Subscription → InboundConnection) for XUI email lookups.

### 3. Bot Handlers (`app/bot/handlers/admin/clients.py`)
Added three new handlers:
- `start_client_search`: Initiates search flow
- `select_search_field`: Handles search field selection
- `process_search_query`: Processes search input and displays results

Modified `show_clients` to display a search menu instead of listing all clients.

### 4. Keyboards (`app/bot/keyboards/inline.py`)
Added `get_client_search_keyboard()` with search options:
- 👤 По имени (By name)
- 📧 По email (By email)
- 📱 По Telegram ID (By Telegram ID)
- 🔗 По XUI email (By XUI email)
- 🔍 Комплексный поиск (Complex search)

Updated `get_clients_keyboard()` to include "Поиск клиентов" button.

Updated keyboard exports in `app/bot/keyboards/__init__.py`.

## User Flow

1. **Main Menu**: Admin clicks "Управление клиентами"
2. **Search Menu**: Displays options for search and adding clients
3. **Field Selection**: Admin selects search criteria
4. **Query Input**: Admin enters search term
5. **Results**: Displays matching clients with action buttons
6. **Client Actions**: Can view details, edit, enable/disable, delete found clients

## Search Capabilities

### Smart Text Processing
- **Case-insensitive**: "ivan", "IVAN", "Ivan" all find "Ivan"
- **Space normalization**: "Иван  Петров" → "Иван Петров"
- **Special character removal**: "Иван,Петров!" → "Иван Петров" (except for emails)
- **Email normalization**: "  test@example.com  " → "test@example.com"

### Individual Field Search
- **Name**: Multi-word partial matching
  - "Иван" finds "Иван Петров", "Петров Иван", "Иванов"
  - "Иван Петров" finds "Петров Иван" (any word match)
  - Supports Cyrillic and Latin characters
- **Email**: Partial case-insensitive matching
  - "test" finds "test@example.com", "mytest@domain.com"
  - "example.com" finds all emails from that domain
  - Normalized to lowercase automatically
- **Telegram ID**: Exact matching
  - "123456789" finds exact match only
  - Automatically validates input
- **XUI Email**: Partial case-insensitive matching across all inbound connections
  - Searches through all VPN connection emails
  - Useful for finding clients by their VPN email

### Complex Search
Intelligent auto-detection:
- Numbers → searches Telegram ID only
- Contains "@" → searches both client and XUI emails
- Text → searches client name with multi-word support
- Example queries:
  - "123456789" → Telegram ID
  - "test@example.com" → Both email fields
  - "Иван Петров" → Name (matches "Петров Иван", "Иванов", etc.)

## Benefits

1. **Scalability**: No performance impact with large client counts
2. **Flexibility**: Multiple search criteria for different use cases
3. **User Experience**: Faster access to specific clients
4. **Data Coverage**: Searches across client data and related XUI data
5. **Maintainability**: Clean separation of concerns (service layer for search logic)

## Technical Details

- **SQLAlchemy**: Uses `ilike()` for case-insensitive partial matching
- **Joins**: Properly handles joins across Client → Subscription → InboundConnection
- **Distinct**: Prevents duplicate results when joining tables
- **Eager Loading**: Uses `selectinload()` for efficient relationship loading
- **State Management**: Properly clears FSM state after search completion

## Future Enhancements (Optional)

1. Add pagination for search results
2. Add advanced filters (date ranges, active status, etc.)
3. Add search history/saved searches
4. Add sorting options for results
5. Add export functionality for search results

## Testing Recommendations

1. Test search with various criteria (name, email, Telegram ID, XUI email)
2. Test complex search with different query types
3. Test with empty results
4. Test with single result
5. Test with multiple results
6. Verify navigation flow works correctly
7. Test client actions from search results
