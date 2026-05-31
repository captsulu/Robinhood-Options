#!/usr/bin/env python3
"""
test_dashboard.py
=================
Comprehensive automated test suite for the Robinhood Monitor dashboard.

Tests:
  1. Python syntax for all .py files
  2. JS syntax for all .js files (requires node)
  3. Flask app import and route registration
  4. All API endpoints return 200 with correct response shapes
  5. Dashboard HTML renders without Jinja errors
  6. All required DOM IDs present in rendered HTML
  7. Script tags in correct load order
  8. All template onclick methods exist in JS classes
  9. No orphaned window bridge calls
 10. CSS file not truncated (key selectors present)
 11. Balanced <div>/<div> tags in all partials

Run:  python tests/test_dashboard.py
      python tests/test_dashboard.py -v   (verbose)
"""
import ast, glob, json, os, re, subprocess, sys, unittest
from pathlib import Path

# Locate project root
HERE     = Path(__file__).parent
ROOT     = HERE.parent
STATIC   = ROOT / 'static' / 'js'
TMPL     = ROOT / 'templates'
CSS      = ROOT / 'static' / 'css' / 'main.css'
PARTIALS = TMPL / 'partials'

sys.path.insert(0, str(ROOT))
os.environ.setdefault('FLASK_TESTING', '1')


# ── Helpers ──────────────────────────────────────────────────────────────────

def _all_py():
    return glob.glob(str(ROOT / '**' / '*.py'), recursive=True)

def _all_js():
    return list(STATIC.glob('*.js'))

def _all_html():
    return list(PARTIALS.glob('*.html')) + [TMPL / 'dashboard.html']

def _rendered_html():
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    with flask_app.app.test_client() as c:
        return c.get('/').data.decode('utf-8', 'replace')

def _get_json(route):
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    with flask_app.app.test_client() as c:
        r = c.get(route)
        return r.status_code, json.loads(r.data)


# ============================================================================
class TestPythonSyntax(unittest.TestCase):
    """Every .py file must compile without errors."""
    def test_all_python_files(self):
        import py_compile
        errors = []
        for f in _all_py():
            if '__pycache__' in f or 'test_' in Path(f).name:
                continue
            try:
                py_compile.compile(f, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))
        self.assertFalse(errors, 'Python syntax errors:\n' + '\n'.join(errors))


class TestJsSyntax(unittest.TestCase):
    """Every .js file must pass `node --check`."""
    def test_all_js_files(self):
        node = subprocess.run(['which', 'node'], capture_output=True, text=True)
        if node.returncode != 0:
            self.skipTest('node not installed')
        errors = []
        for f in _all_js():
            r = subprocess.run(['node', '--check', str(f)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f'{f.name}: {r.stderr.strip()}')
        self.assertFalse(errors, 'JS syntax errors:\n' + '\n'.join(errors))


class TestFlaskApp(unittest.TestCase):
    """Flask app imports cleanly and registers all expected routes."""
    REQUIRED_ROUTES = [
        '/', '/api/positions', '/api/cash', '/api/config',
        '/api/transfers', '/api/alerts',
        '/api/stock-universe', '/api/stock-universe/stats',
        '/api/stock-universe/scan', '/api/stock-universe/scan/status',
        '/api/put-screen', '/api/put-screen/stats',
        '/api/put-screen/scan', '/api/put-screen/scan/status',
        '/api/covered-calls', '/api/covered-calls/stats',
        '/api/covered-calls/scan', '/api/covered-calls/scan/status',
        '/api/grade/<symbol>', '/api/stock-detail/<symbol>',
    ]

    def test_import(self):
        import app
        self.assertTrue(hasattr(app, 'app'))

    def test_routes_registered(self):
        import app as flask_app
        registered = {str(r) for r in flask_app.app.url_map.iter_rules()}
        missing = [r for r in self.REQUIRED_ROUTES if r not in registered]
        self.assertFalse(missing, 'Missing routes: ' + str(missing))


class TestApiEndpoints(unittest.TestCase):
    """All API endpoints return HTTP 200 with expected JSON keys."""
    ENDPOINTS = [
        ('/api/positions',              ['positions']),
        ('/api/cash',                   ['live']),
        ('/api/alerts',                 []),
        ('/api/config',                 ['days_before_expiration_warning']),
        ('/api/transfers',              []),
        ('/api/stock-universe',         ['stocks', 'total']),
        ('/api/stock-universe/stats',   ['total']),
        ('/api/stock-universe/scan/status', ['running']),
        ('/api/put-screen',             ['opportunities', 'total']),
        ('/api/put-screen/stats',       ['total']),
        ('/api/put-screen/scan/status', ['running']),
        ('/api/covered-calls',          ['opportunities', 'total']),
        ('/api/covered-calls/stats',    ['total']),
        ('/api/covered-calls/scan/status', ['running']),
    ]

    def test_all_endpoints(self):
        errors = []
        for route, required_keys in self.ENDPOINTS:
            try:
                status, data = _get_json(route)
                if status != 200:
                    errors.append(f'{route}: status={status}')
                    continue
                missing = [k for k in required_keys if k not in data]
                if missing:
                    errors.append(f'{route}: missing keys {missing}, got {list(data.keys())}')
            except Exception as e:
                errors.append(f'{route}: exception {e}')
        self.assertFalse(errors, 'API errors:\n' + '\n'.join(errors))


class TestHtmlRender(unittest.TestCase):
    """Dashboard renders without Jinja error and contains all required DOM IDs."""
    REQUIRED_IDS = [
        # Tab panes
        'pane-dashboard', 'pane-funds', 'pane-stockscreen', 'pane-putscreen',
        'pane-coveredcalls', 'pane-collateral', 'pane-transfers', 'pane-logs',
        # Tab buttons
        'tab-dashboard', 'tab-funds', 'tab-stockscreen', 'tab-putscreen',
        'tab-coveredcalls', 'tab-collateral', 'tab-transfers', 'tab-logs',
        # Dashboard cards
        'cardTotal', 'cardSafe', 'cardWarning', 'cardCritical', 'cardTolerance',
        # Positions tables
        'positionsBody', 'zdteBody', 'zdte-section',
        # Stock screen modal
        'ssModal', 'ssModalBody', 'ssModalSymbol', 'ssModalName', 'ssModalGrade',
        # Covered calls popup
        'ccPopup', 'ccPopupOverlay', 'ccPopupBody', 'ccPopupTitle', 'ccPopupGrade',
        # CC filter buttons
        'ccHideOwnedBtn', 'ccAffordBtn', 'ccHideRiskBtn',
        # Grade sidebar
        'gradeSidebar', 'gsOverlay', 'gsGradeBig', 'gsSidebarBody',
        # Settings
        'settingsOverlay', 'tolSlider', 'tolValue',
        # Header
        'sessionLabel', 'lastScan', 'statusBadge', 'scanBtn',
    ]

    REQUIRED_SCRIPTS = [
        'utils.js', 'GradeManager.js', 'PositionsManager.js',
        'CashManager.js', 'ChartManager.js', 'TransferManager.js',
        'LogManager.js', 'TabManager.js', 'MonitorApp.js',
        # StockScreen split: core then prototype extensions
        'StockScreenCore.js', 'StockScreenModal.js', 'StockScreenScan.js',
        'PutScreenManager.js',
        # CoveredCalls split: core then prototype extensions
        'CoveredCallCore.js', 'CoveredCallPopup.js', 'CoveredCallScan.js',
        'main.js',
    ]

    def setUp(self):
        self._html = _rendered_html()

    def test_renders_ok(self):
        self.assertIn('Robinhood Options Monitor', self._html)
        self.assertNotIn('jinja2.exceptions', self._html.lower())

    def test_required_ids(self):
        missing = [id for id in self.REQUIRED_IDS
                   if f'id="{id}"' not in self._html]
        self.assertFalse(missing, 'Missing DOM IDs:\n  ' + '\n  '.join(missing))

    def test_script_load_order(self):
        scripts = re.findall(r'<script src="/static/js/([^"]+)"', self._html)
        missing = [s for s in self.REQUIRED_SCRIPTS if s not in scripts]
        self.assertFalse(missing, 'Missing script tags: ' + str(missing))
        # main.js must be last
        if 'main.js' in scripts:
            self.assertEqual(scripts[-1], 'main.js',
                             'main.js must be the last script tag')
        # MonitorApp must load before StockScreen and CoveredCall core files
        for core in ('StockScreenCore.js', 'CoveredCallCore.js'):
            if 'MonitorApp.js' in scripts and core in scripts:
                self.assertLess(scripts.index('MonitorApp.js'),
                                scripts.index(core),
                                f'MonitorApp.js must load before {core}')
        # Core files must load before their prototype-extension siblings
        for core, ext in (('StockScreenCore.js', 'StockScreenModal.js'),
                          ('StockScreenCore.js', 'StockScreenScan.js'),
                          ('CoveredCallCore.js', 'CoveredCallPopup.js'),
                          ('CoveredCallCore.js', 'CoveredCallScan.js')):
            if core in scripts and ext in scripts:
                self.assertLess(scripts.index(core), scripts.index(ext),
                                f'{core} must load before {ext}')


class TestOnclickMethods(unittest.TestCase):
    """Every onclick method called in templates exists on its JS class."""
    # Maps window.X prefix to list of JS files that together define all methods
    CLASS_FILES = {
        'window.stockScreen': [
            STATIC / 'StockScreenCore.js',
            STATIC / 'StockScreenModal.js',
            STATIC / 'StockScreenScan.js',
        ],
        'window.putScreen': [STATIC / 'PutScreenManager.js'],
        'window.coveredCalls': [
            STATIC / 'CoveredCallCore.js',
            STATIC / 'CoveredCallPopup.js',
            STATIC / 'CoveredCallScan.js',
        ],
    }
    GLOBAL_BRIDGES = {
        'toggleSettings', 'triggerScan', 'saveSettings', 'closeGradeSidebar',
        'openGradeSidebar', 'refreshGrade', 'showTab', 'refreshCash',
        'onMarginToggle', 'syncTransfers', 'markCleared', 'toggleSection',
        'takeManualSnapshot', 'refreshCharts', 'event',
    }

    def _methods_in_js(self, paths):
        """Collect all method names from one or more JS files."""
        methods = set()
        path_list = paths if isinstance(paths, list) else [paths]
        for path in path_list:
            src = path.read_text()
            # Class body methods: 2-space indent + name(
            methods |= set(re.findall(r'^\s{2}(\w+)\s*\(', src, re.MULTILINE))
            # Prototype extensions: ClassName.prototype.methodName = function
            methods |= set(re.findall(r'\.prototype\.(\w+)\s*=\s*function', src))
        return methods

    def test_manager_methods(self):
        errors = []
        onclick_re = re.compile(r'onclick="([^"]+)"')
        for html_f in _all_html():
            content = html_f.read_text()
            for call in onclick_re.findall(content):
                for prefix, js_paths in self.CLASS_FILES.items():
                    m = re.match(rf'{re.escape(prefix)}\.(\w+)\(', call)
                    if m:
                        method = m.group(1)
                        methods = self._methods_in_js(js_paths)
                        if method not in methods:
                            names = ', '.join(
                                p.name for p in (js_paths if isinstance(js_paths, list) else [js_paths])
                            )
                            errors.append(
                                f'{html_f.name}: {prefix}.{method}() '
                                f'not found in [{names}]')
        self.assertFalse(errors, 'Missing JS methods:\n' + '\n'.join(errors))

    def test_global_bridges(self):
        errors = []
        onclick_re = re.compile(r'onclick="([^"]+)"')
        for html_f in _all_html():
            content = html_f.read_text()
            for call in onclick_re.findall(content):
                m = re.match(r'(\w+)\(', call.strip())
                if m:
                    fn = m.group(1)
                    if fn not in self.GLOBAL_BRIDGES and not fn.startswith('window'):
                        errors.append(f'{html_f.name}: bare call {fn}() - '
                                      f'check window bridge in main.js')
        self.assertFalse(errors,
                         'Possible missing window bridges:\n' + '\n'.join(errors))


class TestCssCompleteness(unittest.TestCase):
    """CSS must contain key selectors for all major UI components."""
    REQUIRED_SELECTORS = [
        '.tab-pane', '.tab-btn', '.tab-bar',
        '.ss-modal', '.ss-modal-overlay',
        '.grade-sidebar', '.gs-overlay',
        '.cards-row', '.card',
        '.ss-table', '.ss-chip',
        '.ps-tier-legendary', '.ps-tier-epic', '.ps-tier-rare', '.ps-tier-good',
        '.cc-crit-badge',
        '.settings-overlay',
        '.hidden',
    ]

    def test_required_selectors(self):
        css = CSS.read_text()
        missing = [s for s in self.REQUIRED_SELECTORS if s not in css]
        self.assertFalse(missing,
                         'CSS missing selectors:\n  ' + '\n  '.join(missing))

    def test_not_truncated(self):
        css = CSS.read_text().strip()
        self.assertTrue(css.endswith('}'),
                        'CSS appears truncated — does not end with "}"')


class TestDivBalance(unittest.TestCase):
    """Every HTML partial must have balanced <div> / </div> tags."""
    def test_balanced_divs(self):
        errors = []
        for html_f in _all_html():
            content = html_f.read_text()
            opens  = content.count('<div')
            closes = content.count('</div>')
            if opens != closes:
                errors.append(
                    f'{html_f.name}: {opens} <div> vs {closes} </div>')
        self.assertFalse(errors, 'Unbalanced divs:\n' + '\n'.join(errors))


# ============================================================================
if __name__ == '__main__':
    verbose = '-v' in sys.argv
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()
    for cls in [
        TestPythonSyntax, TestJsSyntax, TestFlaskApp, TestApiEndpoints,
        TestHtmlRender, TestOnclickMethods, TestCssCompleteness, TestDivBalance,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
