# Bugfix: Duplicate Route Registration

## Issue
After the initial refactoring, the application failed to start with the error:
```
AssertionError: View function mapping is overwriting an existing endpoint function: browser.clear_cookies
```

## Root Cause
In `app/routes/browser_routes.py`, the `clear_cookies` route was being registered twice:
1. As a placeholder function outside `init_browser_routes()`
2. Inside the `add_clear_cookies_route()` helper function

When both were called during app initialization, Flask detected the duplicate registration and threw an error.

## Fix Applied

### 1. Removed Duplicate Route Definitions
**Before:**
```python
# Inside init_browser_routes()
def init_browser_routes(browser_service, download_service):
    # ... routes
    return browser_bp

# Outside the init function (DUPLICATE!)
@browser_bp.route('/clear-cookies', methods=['POST'])
def clear_cookies():
    pass

# Helper function trying to add it again (DUPLICATE!)
def add_clear_cookies_route(browser_bp, browser_service):
    @browser_bp.route('/clear-cookies', methods=['POST'])
    def clear_cookies():
        # ... actual implementation
```

**After:**
```python
# All routes inside init_browser_routes()
def init_browser_routes(browser_service, download_service, config):
    # ... other routes

    @browser_bp.route('/clear-cookies', methods=['POST'])
    def clear_cookies():
        # ... implementation (ONLY ONE!)

    @browser_bp.route('/test/chrome', methods=['GET'])
    def test_chrome():
        # ... implementation (ONLY ONE!)

    return browser_bp
```

### 2. Updated Function Signature
Added `config` parameter to `init_browser_routes()` so the test endpoint can access Chrome paths:
```python
def init_browser_routes(browser_service, download_service, config):
```

### 3. Simplified app.py
Removed the extra helper function calls:

**Before:**
```python
browser_bp = init_browser_routes(browser_service, download_service)
add_clear_cookies_route(browser_bp, browser_service)  # Duplicate!
add_test_chrome_route(browser_bp, config)  # Duplicate!
flask_app.register_blueprint(browser_bp)
```

**After:**
```python
browser_bp = init_browser_routes(browser_service, download_service, config)
flask_app.register_blueprint(browser_bp)  # Clean!
```

### 4. Updated Imports
Removed unused imports from `app/routes/__init__.py`:

**Before:**
```python
from .browser_routes import init_browser_routes, add_clear_cookies_route, add_test_chrome_route
```

**After:**
```python
from .browser_routes import init_browser_routes
```

## Files Modified
1. ✅ `app/routes/browser_routes.py` - Consolidated all routes inside init function
2. ✅ `app/routes/__init__.py` - Removed unused exports
3. ✅ `app/app.py` - Simplified route registration

## Verification
```bash
# Syntax check
cd app && python -m py_compile app.py routes/browser_routes.py

# Check for duplicate routes
grep -n "clear-cookies" app/routes/browser_routes.py
# Output: Only one match at line 140 ✅

grep -n "test/chrome" app/routes/browser_routes.py
# Output: Only one match at line 155 ✅
```

## Result
✅ Application now starts successfully
✅ All routes properly registered
✅ No duplicate endpoint errors
✅ Cleaner code structure

## Lesson Learned
When using the application factory pattern with Flask blueprints:
- Define ALL routes inside the initialization function
- Avoid creating route decorators at module level
- Pass dependencies (like config) as parameters to init functions
- Don't use helper functions to add routes after blueprint initialization
