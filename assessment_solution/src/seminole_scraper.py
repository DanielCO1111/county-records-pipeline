"""
Seminole County FL Official Records Scraper

This module scrapes official records from Seminole County, FL and converts them
to the North Carolina schema format for system compatibility.

Website: https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from dateutil import parser as date_parser
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService


# Fixed output path for all runs (assignment requirement)
OUTPUT_PATH = Path("outputs") / "seminole_test_results.json"

# Test cases for --run-tests mode
TEST_CASES = [
    {"name": "Smith john jr", "expected_count": 16},   # Single page
    {"name": "Smith john C", "expected_count": 81},    # 3 pages (pagination test)
    {"name": "XYZ ABC", "expected_count": 0},          # No results (false-positive check)
]

# NC schema required keys (exact set)
NC_SCHEMA_KEYS = {
    "instrument_number", "parcel_number", "county", "state", "book", "page",
    "doc_type", "doc_category", "original_doc_type", "book_type",
    "grantors", "grantees", "date", "consideration"
}

# Fields that must always be None (not available in Seminole grid)
MUST_BE_NULL_FIELDS = {"parcel_number", "doc_category", "book_type", "consideration"}


class SeminoleScraper:
    """
    Scraper for Seminole County official records.
    
    Follows conservative schema-first approach:
    - Only populates fields explicitly in the grid
    - Uses null for unavailable fields (not empty lists/strings)
    - Deterministic non-semantic party mapping
    """
    
    # Configuration constants
    BASE_URL = "https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html"
    REQUEST_DELAY = 2  # Seconds between page navigations
    PAGE_TIMEOUT = 60  # Seconds per page
    TOTAL_RUNTIME_LIMIT = 3600  # 1 hour max
    ELEMENT_WAIT_TIMEOUT = 30  # Seconds for element waits
    MAX_RETRIES = 3  # Network failure retries
    
    # Debug artifacts: set to True or set env var SEMINOLE_DEBUG_ARTIFACTS=1 to save screenshots on errors
    DEBUG_ARTIFACTS = False
    
    # Eastern Time timezone for date conversion
    ET_TIMEZONE = pytz.timezone("America/New_York")
    
    def __init__(self, headless: bool = False):
        """
        Initialize the scraper with Selenium WebDriver.
        
        Args:
            headless: Run browser in headless mode
        """
        self.logger = self._setup_logging()
        self.headless = headless
        self.driver = None
        self._setup_driver()
        
    def _setup_logging(self) -> logging.Logger:
        """Configure logging with appropriate format (idempotent)."""
        logger = logging.getLogger("SeminoleScraper")
        logger.setLevel(logging.INFO)
        logger.propagate = False  # avoid duplicate logs from root logger
        
        # Only add handler if none exist (prevents duplicates on multiple instantiations)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _setup_driver(self):
        """Initialize Selenium WebDriver with Chrome."""
        try:
            options = webdriver.ChromeOptions()
            if self.headless:
                options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(self.ELEMENT_WAIT_TIMEOUT)
            
            self.logger.info("WebDriver initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize WebDriver: {e}")
            raise
    
    def close(self):
        """Cleanup WebDriver resources."""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("WebDriver closed")
            except Exception as e:
                self.logger.warning(f"Error closing WebDriver: {e}")
    
    def _should_save_debug_artifacts(self) -> bool:
        """Check if debug artifacts (screenshots) should be saved."""
        return self.DEBUG_ARTIFACTS or os.environ.get("SEMINOLE_DEBUG_ARTIFACTS", "").lower() in ("1", "true", "yes")
    
    def _maybe_screenshot(self, tag: str) -> None:
        """
        Save a debug screenshot if DEBUG_ARTIFACTS is enabled.
        
        Args:
            tag: Descriptive tag for the screenshot filename (e.g., "pagination_fail")
        """
        if not self._should_save_debug_artifacts():
            return
        
        try:
            screenshot_path = Path("outputs") / f"{tag}_{int(time.time())}.png"
            screenshot_path.parent.mkdir(exist_ok=True)
            self.driver.save_screenshot(str(screenshot_path))
            self.logger.info(f"Debug screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.debug(f"Could not save debug screenshot: {e}")
    
    def _with_retries(self, action_name: str, fn):
        """
        Run a callable with retries for transient Selenium/WebDriver errors.
        Intended for coarse operations like driver.get().
        
        Args:
            action_name: Description of the action for logging
            fn: Callable to execute with retries
            
        Returns:
            Result of fn()
            
        Raises:
            Last exception if all retries exhausted
        """
        last_exc = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return fn()
            except (WebDriverException, TimeoutException) as e:
                last_exc = e
                wait_s = min(2 ** (attempt - 1), 8)  # 1,2,4,8...
                self.logger.warning(
                    f"{action_name} failed (attempt {attempt}/{self.MAX_RETRIES}): {e}. "
                    f"Retrying in {wait_s}s..."
                )
                time.sleep(wait_s)
        
        # Exhausted retries
        self.logger.error(f"{action_name} failed after {self.MAX_RETRIES} attempts: {last_exc}")
        raise last_exc
    
    def _safe_click(self, element, description: str):
        """
        Safely click an element with scroll and fallback to JS click.
        
        Args:
            element: WebElement to click
            description: Description for logging
        """
        try:
            # Scroll element into view
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});",
                element
            )
            time.sleep(0.5)  # Brief pause after scroll
            
            # Try normal click
            element.click()
            self.logger.debug(f"{description}: normal click succeeded")
            
        except Exception as e:
            # Fallback to JavaScript click
            self.logger.debug(f"{description}: normal click failed ({e}), using JS click")
            self.driver.execute_script("arguments[0].click();", element)
            self.logger.debug(f"{description}: JS click succeeded")
    
    def _accept_disclaimer_if_present(self):
        """
        Click 'AGREED & ENTER' disclaimer link if present (primary → fallback strategy).
        
        Strategy:
        1. Always start in default content
        2. Try primary selector (CSS + XPath) for <a> element
        3. If not found, try iframes
        4. Always return to default content
        5. Wait for disclaimer to disappear and form to be clickable
        """
        # Target: <a class="btn btn-success">Agreed & Enter</a>
        # XPath: case-insensitive match for "AGREED" and "ENTER" text in <a> element
        disclaimer_xpath = (
            "//a[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agreed') "
            "and contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'enter')]"
        )
        
        try:
            # A. Always start in default content
            self.driver.switch_to.default_content()
            
            # B. Primary attempt: find <a> link in main DOM
            disclaimer_link = None
            try:
                # Try CSS selector first (most specific)
                try:
                    disclaimer_link = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn.btn-success"))
                    )
                    self.logger.info("Found disclaimer link via CSS selector")
                except TimeoutException:
                    # Try XPath fallback
                    disclaimer_link = WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, disclaimer_xpath))
                    )
                    self.logger.info("Found disclaimer link via XPath")
                
                if disclaimer_link:
                    # Scroll into view (for stability)
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", disclaimer_link
                    )
                    time.sleep(0.3)
                    
                    # Use JavaScript click (bypasses visibility/overlay issues)
                    self.driver.execute_script("arguments[0].click();", disclaimer_link)
                    self.logger.info("Clicked disclaimer link in main content (JS click)")
                    
                    # Wait for disclaimer to disappear (staleness)
                    try:
                        WebDriverWait(self.driver, 5).until(
                            EC.staleness_of(disclaimer_link)
                        )
                        self.logger.info("Disclaimer overlay dismissed")
                    except TimeoutException:
                        self.logger.debug("Disclaimer link still present (may be hidden now)")
                    
                    # C. Wait for search form to be clickable
                    WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                        EC.element_to_be_clickable((By.ID, "criteria_full_name"))
                    )
                    self.logger.info("Search form is now clickable")
                    return  # Success!
                    
            except TimeoutException:
                self.logger.info("Disclaimer link not found in main content")
            
            # D. Fallback: try iframes
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if iframes:
                self.logger.info(f"Checking {len(iframes)} iframe(s) for disclaimer...")
                
                for idx, iframe in enumerate(iframes):
                    try:
                        self.driver.switch_to.frame(iframe)
                        
                        # Try CSS first, then XPath
                        iframe_link = None
                        try:
                            iframe_link = WebDriverWait(self.driver, 1).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn.btn-success"))
                            )
                        except TimeoutException:
                            iframe_link = WebDriverWait(self.driver, 1).until(
                                EC.presence_of_element_located((By.XPATH, disclaimer_xpath))
                            )
                        
                        if iframe_link:
                            # Scroll and click with JavaScript
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", iframe_link
                            )
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", iframe_link)
                            self.logger.info(f"Clicked disclaimer link in iframe {idx} (JS click)")
                            
                            # Return to main content
                            self.driver.switch_to.default_content()
                            
                            # Wait for search form to be clickable
                            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                                EC.element_to_be_clickable((By.ID, "criteria_full_name"))
                            )
                            self.logger.info("Search form is now clickable")
                            return  # Success!
                        
                    except TimeoutException:
                        self.driver.switch_to.default_content()
                        continue
            
            # If we get here, no disclaimer button was found
            self.logger.info("No disclaimer button found - may already be dismissed or not required")
            self.driver.switch_to.default_content()
            
        except Exception as e:
            self.logger.error(f"Error handling disclaimer: {e}")
            
            # Debug info
            try:
                self.logger.info(f"Page title: {self.driver.title}")
                self.logger.info(f"Current URL: {self.driver.current_url}")
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                self.logger.info(f"Iframes found: {len(iframes)}")
                self._maybe_screenshot("disclaimer_error")
            except Exception:
                pass
            
            # Always return to default content
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
    
    def _wait_for_results(self) -> bool:
        """
        Wait for igGrid to fully render (patient strategy for slow system).
        
        Strategy:
        1. Wait for #grid_container
        2. Wait for table headers to render (grid structure ready)
        3. Give additional time for data to populate (slow system)
        4. Check pager text
        5. Return True regardless if headers exist (let extraction handle empty data)
        
        Returns:
            True if grid rendered (even if empty), False only on timeout
        """
        try:
            # Give the page time to start processing
            time.sleep(1)
            
            # Wait for igGrid container
            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "grid_container"))
            )
            self.logger.info("igGrid container loaded")
            
            # CRITICAL: Wait for table HEADERS to render (grid structure is ready)
            # This is the definitive signal that the grid has initialized
            self.logger.info("Waiting for igGrid headers to render...")
            
            # Try multiple selectors for header table (igGrid can vary)
            header_cells = None
            for selector in [
                "table.ui-iggrid-headertable th",
                "#grid_container table thead th",
                "#grid_container th",
                "table thead th",  # Generic fallback
            ]:
                try:
                    self.logger.debug(f"Trying header selector: {selector}")
                    header_cells = WebDriverWait(self.driver, 10).until(
                        lambda d: d.find_elements(By.CSS_SELECTOR, selector) or None
                    )
                    if header_cells and len(header_cells) > 0:
                        self.logger.info(f"Found headers with selector: {selector}")
                        break
                except TimeoutException:
                    continue
            
            if not header_cells or len(header_cells) == 0:
                self.logger.error("Could not find any header cells - grid may not have rendered")
                # Continue anyway - extraction will handle it
            else:
                self.logger.info(f"igGrid headers rendered: {len(header_cells)} columns")
            
            # Give the SLOW system additional time to populate data rows
            # Don't trust early "0 records" - grid might still be loading
            self.logger.info("Waiting for data to populate (slow system)...")
            time.sleep(3)  # Patient wait for data loading
            
            # Now check pager label (should be updated by now)
            try:
                pager_label = self.driver.find_element(By.ID, "grid_pager_label")
                pager_text = pager_label.text.strip()
                self.logger.info(f"igGrid pager text (after wait): '{pager_text}'")
                
                # Parse total records
                match = re.search(r'^\s*\d+\s*-\s*\d+\s+of\s+(\d+)\s+records?\s*$', pager_text, re.IGNORECASE)
                if match:
                    total_records = int(match.group(1))
                    self.logger.info(f"Parsed total records: {total_records}")
                else:
                    self.logger.debug(f"Could not parse pager text: '{pager_text}'")
                    
            except Exception as e:
                self.logger.debug(f"Could not read pager label: {e}")
            
            # ALWAYS return True if headers rendered - let extraction handle empty data
            # This prevents exiting before the grid finishes loading
            self.logger.info("igGrid structure ready - proceeding to extraction")
            return True
            
        except TimeoutException:
            self.logger.error("Timeout waiting for igGrid")
            
            # Debug snapshot
            try:
                self.logger.error(f"URL: {self.driver.current_url}")
                self.logger.error(f"Title: {self.driver.title}")
                
                # Check what elements with "record" text exist
                record_els = self.driver.find_elements(By.XPATH, 
                    "//*[contains(text(), 'record') or contains(text(), 'Record')]")
                self.logger.error(f"Found {len(record_els)} elements with 'record' text")
                
                # Try to find pager container
                try:
                    grid = self.driver.find_element(By.ID, "grid_container")
                    pager_area = grid.find_elements(By.XPATH, ".//*[contains(@class, 'pager')]")
                    if pager_area:
                        outer_html = pager_area[0].get_attribute("outerHTML")
                        self.logger.error(f"Pager container HTML: {outer_html[:200]}")
                except Exception:
                    pass
            except Exception:
                pass
            
            self._maybe_screenshot("iggrid_timeout")
            return False
        
        except Exception as e:
            self.logger.error(f"Error waiting for igGrid: {type(e).__name__}: {e}")
            return False
    
    def _get_pagination_info(self) -> tuple[int, int]:
        """
        Extract current page and total pages from igGrid pager.
        
        Uses the pager label text "X - Y of Z records" to calculate pages.
        
        Returns:
            (current_page, total_pages) tuple
        """
        try:
            # Read igGrid pager label
            pager_label = self.driver.find_element(By.ID, "grid_pager_label")
            pager_text = pager_label.text.strip()
            
            # Parse "1 - 30 of 81 records" format
            match = re.search(r'^\s*(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+records?\s*$', pager_text, re.IGNORECASE)
            
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                total = int(match.group(3))
                
                # Calculate current page and total pages
                # Assuming 30 records per page (default igGrid page size)
                records_per_page = end - start + 1  # Actual records on this page
                if records_per_page == 0:
                    records_per_page = 30  # Default
                
                current_page = (start - 1) // records_per_page + 1 if start > 0 else 1
                total_pages = (total + records_per_page - 1) // records_per_page
                
                return current_page, total_pages
            
            # Fallback: assume single page
            return 1, 1
            
        except Exception as e:
            self.logger.debug(f"Error parsing pagination: {e}")
            return 1, 1
    
    def _normalize_header(self, text: str) -> str:
        """Normalize header text for matching."""
        if not text:
            return ""
        # Replace NBSP with space, lowercase, strip, collapse whitespace
        return " ".join(text.replace("\u00a0", " ").lower().strip().split())
    
    def _extract_page_results(self) -> List[Dict[str, Any]]:
        """
        Extract all rows from igGrid (Infragistics jQuery grid).
        
        Strategy:
        1. Get headers from table.ui-iggrid-headertable
        2. Get data rows from #grid_scroll table tbody tr
        3. Map cell values to headers by index
        4. Fallback: Try reading igGrid dataSource via JavaScript
        
        Returns:
            List of raw row data dictionaries
        """
        rows_data = []
        
        try:
            # A) Get headers from igGrid - try multiple selectors (same as wait_for_results)
            headers = []
            for selector in [
                "#grid_container table thead th",
                "table.ui-iggrid-headertable th",
                "#grid_container th",
            ]:
                try:
                    header_cells = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if header_cells and len(header_cells) > 0:
                        headers = [cell.text.strip() for cell in header_cells if cell.text.strip()]
                        if headers:
                            self.logger.info(f"Extracted headers using selector: {selector}")
                            break
                except Exception as e:
                    self.logger.debug(f"Selector {selector} failed: {e}")
                    continue
            
            if headers:
                normalized_headers = [self._normalize_header(h) for h in headers]
                self.logger.info(f"igGrid headers (original): {headers}")
                self.logger.info(f"igGrid headers (normalized): {normalized_headers}")
            else:
                self.logger.error("Could not extract igGrid headers with any selector!")
            
            # B) Get data rows from #grid_scroll table
            try:
                grid_scroll = self.driver.find_element(By.ID, "grid_scroll")
                data_table = grid_scroll.find_element(By.TAG_NAME, "table")
                rows = data_table.find_elements(By.CSS_SELECTOR, "tbody tr")
                
                self.logger.info(f"Found {len(rows)} rows in #grid_scroll table")
                
                for row_idx, row in enumerate(rows):
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        
                        if len(cells) == 0:
                            continue
                        
                        # Extract cell values
                        cell_values = [cell.text.strip() for cell in cells]
                        
                        # C) Map to column names by index
                        row_data = {}
                        if headers:
                            for i, header in enumerate(headers):
                                if i < len(cell_values):
                                    row_data[header] = cell_values[i] if cell_values[i] else None
                        else:
                            # Fallback: use generic column indices
                            for i, value in enumerate(cell_values):
                                row_data[f"col_{i}"] = value if value else None
                        
                        rows_data.append(row_data)
                        
                        # Log first row keys for debugging
                        if row_idx == 0 and row_data:
                            self.logger.info(f"First row keys: {list(row_data.keys())}")
                        
                    except Exception as e:
                        self.logger.debug(f"Error extracting row {row_idx}: {e}")
                        continue
                
                self.logger.info(f"Extracted {len(rows_data)} rows from igGrid")
                
            except Exception as e:
                self.logger.warning(f"Could not extract rows from #grid_scroll: {e}")
            
            # D) Fallback: Try reading igGrid dataSource via JavaScript
            if len(rows_data) == 0 and headers:
                self.logger.info("Attempting JavaScript fallback to read igGrid dataSource...")
                try:
                    js_data = self.driver.execute_script("""
                        try {
                            const $ = window.jQuery || window.$;
                            if (!$) return null;
                            const grid = $("#grid_container").data("igGrid");
                            if (!grid) return null;
                            const dataSource = grid.dataSource;
                            if (!dataSource) return null;
                            return dataSource.data() || dataSource.dataView() || null;
                        } catch (e) {
                            return null;
                        }
                    """)
                    
                    if js_data and isinstance(js_data, list):
                        self.logger.info(f"Retrieved {len(js_data)} rows from igGrid dataSource via JS")
                        rows_data = js_data
                    else:
                        self.logger.debug("JavaScript fallback: no data available")
                        
                except Exception as e:
                    self.logger.debug(f"JavaScript fallback failed: {e}")
            
            # Final check: if UI shows records but we got 0 rows, debug
            if len(rows_data) == 0:
                try:
                    record_text_elements = self.driver.find_elements(By.XPATH, 
                        "//*[contains(text(), 'record') or contains(text(), 'Record')]")
                    if record_text_elements:
                        record_text = record_text_elements[0].text
                        if any(char.isdigit() and char != '0' for char in record_text):
                            # Non-zero record count but no rows extracted
                            self.logger.warning(f"Record count shows data but extracted 0 rows: '{record_text}'")
                            self._maybe_screenshot("extraction_mismatch")
                except Exception:
                    pass
            
        except Exception as e:
            self.logger.error(f"Error in igGrid extraction: {type(e).__name__}: {e}")
        
        return rows_data
    
    def _get_first_row_instrument(self) -> Optional[str]:
        """Get the instrument number from the first data row for change detection."""
        try:
            first_cell = self.driver.find_element(
                By.CSS_SELECTOR, "#grid_scroll table tbody tr:first-child td:first-child"
            )
            return first_cell.text.strip()
        except Exception:
            return None
    
    def _wait_for_loading_complete(self):
        """Wait for igGrid loading indicator to appear then disappear."""
        try:
            # igGrid shows #grid_container_loading during page transitions
            loading_selector = "#grid_container_loading"
            
            # Brief wait for loading to appear (may not always show)
            try:
                WebDriverWait(self.driver, 1).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, loading_selector))
                )
                self.logger.debug("Loading indicator appeared")
            except TimeoutException:
                pass  # Loading may be too fast to catch
            
            # Wait for loading to disappear
            WebDriverWait(self.driver, self.PAGE_TIMEOUT).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, loading_selector))
            )
            self.logger.debug("Loading indicator hidden")
            
        except Exception as e:
            self.logger.debug(f"Loading wait skipped: {e}")
    
    def _find_visible_next_button(self) -> Optional[Any]:
        """
        Find the REAL visible and enabled Next button.
        
        igGrid's Next control is a DIV element (not an <a> inside it):
          <div class="ui-iggrid-nextpage ui-iggrid-paging-item ui-state-default" 
               title="Next page" tabindex="0">…</div>
        
        When disabled (last page), igGrid adds "ui-state-disabled" to the class.
        
        Returns:
            The visible/enabled Next element, or None if not found/disabled
        """
        # Selectors targeting the div directly (NOT looking for <a> inside)
        # Ordered from most specific to least specific
        selectors = [
            "#grid_pager .ui-iggrid-nextpage",
            "div.ui-iggrid-nextpage[title='Next page']",
            ".ui-iggrid-paging .ui-iggrid-nextpage",
            "//div[@id='grid_pager']//div[contains(@class,'ui-iggrid-nextpage')]",
        ]
        
        for selector in selectors:
            try:
                # Use find_elements to get ALL matches
                if selector.startswith("//"):
                    elements = self.driver.find_elements(By.XPATH, selector)
                else:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                
                for idx, elem in enumerate(elements):
                    try:
                        # Check if displayed AND enabled
                        is_displayed = elem.is_displayed()
                        is_enabled = elem.is_enabled()
                        
                        # Check element class for disabled state
                        # igGrid adds "ui-state-disabled" when on the last page
                        elem_class = elem.get_attribute("class") or ""
                        elem_disabled = "ui-state-disabled" in elem_class
                        
                        # Log diagnostics
                        outer_html = elem.get_attribute("outerHTML") or ""
                        outer_snippet = outer_html[:150] + "..." if len(outer_html) > 150 else outer_html
                        
                        self.logger.debug(
                            f"Next candidate [{selector}][{idx}]: "
                            f"displayed={is_displayed}, enabled={is_enabled}, "
                            f"class='{elem_class}', disabled={elem_disabled}, "
                            f"html={outer_snippet}"
                        )
                        
                        # Select if visible, enabled, and not disabled
                        if is_displayed and is_enabled and not elem_disabled:
                            self.logger.info(
                                f"Selected Next button: selector='{selector}', index={idx}, "
                                f"displayed={is_displayed}, disabled={elem_disabled}"
                            )
                            return elem
                        elif elem_disabled:
                            self.logger.info(
                                f"Next button found but DISABLED (last page): selector='{selector}'"
                            )
                            return None  # Explicitly return None - we're on last page
                            
                    except StaleElementReferenceException:
                        continue
                        
            except Exception as e:
                self.logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        return None
    
    def _click_next_page(self, pager_before: str, first_instrument_before: Optional[str]) -> bool:
        """
        Click igGrid 'Next' page button and wait for page to actually change.
        
        Strategy - try multiple click methods with SHORT timeouts, fail fast to next method:
        1. jQuery trigger (igGrid uses jQuery event handlers)
        2. Keyboard: focus + Enter key
        3. Mouse events: mousedown + mouseup
        4. ActionChains click
        5. Native JS click
        6. igGrid paging API directly
        
        Args:
            pager_before: Current pager label text (e.g., "1 - 30 of 81 records")
            first_instrument_before: Current first row instrument # (for change detection)
        
        Returns:
            True if successfully navigated to next page, False otherwise
        """
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys
        
        # Short timeout for each click attempt - fail fast to try next method
        CLICK_WAIT_TIMEOUT = 5
        
        def check_pager_changed() -> bool:
            """Check if pager label has changed from initial state."""
            try:
                current = self.driver.find_element(By.ID, "grid_pager_label").text.strip()
                return current != pager_before
            except Exception:
                return False
        
        def wait_for_pager_change(timeout: int = CLICK_WAIT_TIMEOUT) -> bool:
            """Wait for pager to change with given timeout."""
            try:
                WebDriverWait(self.driver, timeout).until(lambda d: check_pager_changed())
                return True
            except TimeoutException:
                return False
        
        try:
            # Find the visible Next button
            next_button = self._find_visible_next_button()
            
            if not next_button:
                self.logger.info("No visible/enabled Next button found - may be last page")
                return False
            
            pager_changed = False
            
            # ============================================================
            # METHOD 1: jQuery trigger (igGrid uses jQuery event handlers)
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 1: jQuery trigger click...")
                    self.driver.execute_script("""
                        var el = arguments[0];
                        if (window.jQuery || window.$) {
                            var $ = window.jQuery || window.$;
                            $(el).trigger('click');
                        }
                    """, next_button)
                    self._wait_for_loading_complete()
                    if wait_for_pager_change():
                        pager_changed = True
                        self.logger.info("Method 1 (jQuery trigger) succeeded!")
                    else:
                        self.logger.debug("Method 1 (jQuery trigger) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 1 (jQuery trigger) failed: {e}")
            
            # ============================================================
            # METHOD 2: Keyboard - focus + Enter key
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 2: Keyboard (focus + Enter)...")
                    # Re-find button in case it became stale
                    next_button = self._find_visible_next_button()
                    if next_button:
                        # Focus the element
                        self.driver.execute_script("arguments[0].focus();", next_button)
                        time.sleep(0.1)
                        # Send Enter key
                        next_button.send_keys(Keys.ENTER)
                        self._wait_for_loading_complete()
                        if wait_for_pager_change():
                            pager_changed = True
                            self.logger.info("Method 2 (Keyboard Enter) succeeded!")
                        else:
                            self.logger.debug("Method 2 (Keyboard Enter) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 2 (Keyboard) failed: {e}")
            
            # ============================================================
            # METHOD 3: Mouse events (mousedown + mouseup)
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 3: Mouse events (mousedown + mouseup)...")
                    next_button = self._find_visible_next_button()
                    if next_button:
                        self.driver.execute_script("""
                            var el = arguments[0];
                            var evtDown = new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window});
                            var evtUp = new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window});
                            var evtClick = new MouseEvent('click', {bubbles: true, cancelable: true, view: window});
                            el.dispatchEvent(evtDown);
                            el.dispatchEvent(evtUp);
                            el.dispatchEvent(evtClick);
                        """, next_button)
                        self._wait_for_loading_complete()
                        if wait_for_pager_change():
                            pager_changed = True
                            self.logger.info("Method 3 (Mouse events) succeeded!")
                        else:
                            self.logger.debug("Method 3 (Mouse events) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 3 (Mouse events) failed: {e}")
            
            # ============================================================
            # METHOD 4: ActionChains (Selenium human-like click)
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 4: ActionChains click...")
                    next_button = self._find_visible_next_button()
                    if next_button:
                        actions = ActionChains(self.driver)
                        actions.move_to_element(next_button).pause(0.2).click().perform()
                        self._wait_for_loading_complete()
                        if wait_for_pager_change():
                            pager_changed = True
                            self.logger.info("Method 4 (ActionChains) succeeded!")
                        else:
                            self.logger.debug("Method 4 (ActionChains) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 4 (ActionChains) failed: {e}")
            
            # ============================================================
            # METHOD 5: Native JavaScript click
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 5: Native JS click...")
                    next_button = self._find_visible_next_button()
                    if next_button:
                        self.driver.execute_script("arguments[0].click();", next_button)
                        self._wait_for_loading_complete()
                        if wait_for_pager_change():
                            pager_changed = True
                            self.logger.info("Method 5 (JS click) succeeded!")
                        else:
                            self.logger.debug("Method 5 (JS click) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 5 (JS click) failed: {e}")
            
            # ============================================================
            # METHOD 6: igGrid Paging API directly
            # ============================================================
            if not pager_changed:
                try:
                    self.logger.info("Method 6: igGrid Paging API...")
                    # Try multiple igGrid API approaches
                    api_scripts = [
                        '$("#grid_container").igGridPaging("pageIndex", $("#grid_container").igGridPaging("pageIndex") + 1);',
                        '$("#grid").igGridPaging("pageIndex", $("#grid").igGridPaging("pageIndex") + 1);',
                        'var grid = $("#grid_container").data("igGrid"); if(grid && grid.dataBind) { var pg = grid.element.data("igGridPaging"); if(pg) pg.pageIndex(pg.pageIndex() + 1); }',
                    ]
                    for script in api_scripts:
                        try:
                            self.driver.execute_script(script)
                            self._wait_for_loading_complete()
                            time.sleep(0.5)
                            if check_pager_changed():
                                pager_changed = True
                                self.logger.info(f"Method 6 (igGrid API) succeeded!")
                                break
                        except Exception:
                            continue
                    if not pager_changed:
                        self.logger.debug("Method 6 (igGrid API) - pager didn't change")
                except Exception as e:
                    self.logger.debug(f"Method 6 (igGrid API) failed: {e}")
            
            # ============================================================
            # Final check
            # ============================================================
            if not pager_changed:
                pager_current = self.driver.find_element(By.ID, "grid_pager_label").text.strip()
                self.logger.error(
                    f"All 6 pagination methods failed! "
                    f"pager_before='{pager_before}', pager_current='{pager_current}'"
                )
                self._maybe_screenshot("pagination_fail")
                return False
            
            # Log successful pager change
            pager_after = self.driver.find_element(By.ID, "grid_pager_label").text.strip()
            self.logger.info(f"Pager changed: '{pager_before}' → '{pager_after}'")
            
            # Wait for first row instrument to change (ensures grid data refreshed)
            # The pager label can update before rows repaint
            if first_instrument_before:
                try:
                    self.logger.debug(f"Waiting for first row instrument to change from '{first_instrument_before}'...")
                    WebDriverWait(self.driver, self.PAGE_TIMEOUT).until(
                        lambda d: self._get_first_row_instrument() != first_instrument_before
                    )
                    new_first_instrument = self._get_first_row_instrument()
                    self.logger.info(f"First row instrument changed: '{first_instrument_before}' → '{new_first_instrument}'")
                except TimeoutException:
                    self.logger.warning(
                        f"First row instrument still '{first_instrument_before}' after {self.PAGE_TIMEOUT}s - "
                        f"data may be stale, but continuing..."
                    )
            
            # Give igGrid a moment to fully render new page data
            time.sleep(self.REQUEST_DELAY)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error clicking next page: {type(e).__name__}: {e}")
            return False
    
    def _parse_pager_label(self) -> tuple[int, int, int]:
        """
        Parse the pager label to get (start, end, total) record numbers.
        
        Returns:
            (start, end, total) tuple, or (0, 0, 0) if parsing fails
        """
        try:
            pager_label = self.driver.find_element(By.ID, "grid_pager_label")
            pager_text = pager_label.text.strip()
            
            # Parse "1 - 30 of 81 records" format
            match = re.search(r'^\s*(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+records?\s*$', pager_text, re.IGNORECASE)
            
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                total = int(match.group(3))
                return start, end, total
            
            return 0, 0, 0
            
        except Exception as e:
            self.logger.debug(f"Error parsing pager label: {e}")
            return 0, 0, 0
    
    def _handle_pagination(self, all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Handle pagination and collect all results across multiple pages.
        
        Uses pager label parsing (end >= total) as the authoritative stop condition,
        NOT an internal page counter.
        
        Args:
            all_rows: Initial rows from first page
            
        Returns:
            Complete list of all rows from all pages
        """
        start_time = time.time()
        page_count = 1  # Just for logging
        previous_first_instrument = self._get_first_row_instrument()
        
        while True:
            # Check total runtime limit
            if time.time() - start_time > self.TOTAL_RUNTIME_LIMIT:
                self.logger.error(
                    f"Hit maximum runtime of {self.TOTAL_RUNTIME_LIMIT}s after {page_count} pages"
                )
                break
            
            # Parse pager label to determine if we're on the last page
            # This is the AUTHORITATIVE stop condition
            start, end, total = self._parse_pager_label()
            self.logger.info(f"Pager: {start} - {end} of {total} records (page {page_count})")
            
            # Stop condition: end >= total means we're showing the last records
            if end >= total:
                self.logger.info(f"Reached last page (showing records {start}-{end} of {total})")
                break
            
            # Safety: if total is 0 or invalid, stop
            if total == 0:
                self.logger.warning("Pager shows 0 total records - stopping pagination")
                break
            
            # Get current state BEFORE clicking (for change detection)
            pager_before = self.driver.find_element(By.ID, "grid_pager_label").text.strip()
            first_instrument_before = self._get_first_row_instrument()
            
            # Try to click Next - pass current state for deterministic wait
            if not self._click_next_page(pager_before, first_instrument_before):
                self.logger.info("Could not navigate to next page - ending pagination")
                break
            
            page_count += 1
            
            # Extract rows from new page
            try:
                page_rows = self._extract_page_results()
                
                # Safety check: verify we got different data (prevent infinite loop)
                current_first_instrument = self._get_first_row_instrument()
                if current_first_instrument == previous_first_instrument:
                    self.logger.error(
                        f"Data didn't change after pagination! "
                        f"First instrument still '{current_first_instrument}' - stopping to prevent infinite loop"
                    )
                    break
                
                previous_first_instrument = current_first_instrument
                all_rows.extend(page_rows)
                self.logger.info(
                    f"Page {page_count}: collected {len(page_rows)} rows "
                    f"(total: {len(all_rows)})"
                )
                
            except TimeoutException:
                self.logger.error(f"Page {page_count} timed out - stopping pagination")
                break
            except Exception as e:
                self.logger.error(f"Error on page {page_count}: {e}")
                break
        
        return all_rows
    
    def _parse_date_with_timezone(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string and convert to ISO 8601 with Eastern Time timezone.
        
        Args:
            date_str: Date string from grid (e.g., "01/15/2024")
            
        Returns:
            ISO 8601 string with timezone (e.g., "2024-01-15T20:00:00-05:00")
            or None if parsing fails
        """
        if not date_str:
            return None
        
        try:
            # Parse date flexibly
            dt = date_parser.parse(date_str)
            
            # If no timezone info, assume it's already in ET
            if dt.tzinfo is None:
                dt = self.ET_TIMEZONE.localize(dt)
            else:
                # Convert to ET if it has a different timezone
                dt = dt.astimezone(self.ET_TIMEZONE)
            
            return dt.isoformat()
            
        except Exception as e:
            self.logger.warning(f"Failed to parse date '{date_str}': {e}")
            return None
    
    def _transform_to_nc_schema(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform FL grid rows to NC schema format.
        
        CRITICAL RULES:
        - Use null for unavailable fields (not empty lists/strings)
        - doc_category, book_type, consideration, parcel_number: always null
        - grantors/grantees: list if present, null if missing (NOT [])
        
        Args:
            raw_rows: Raw row data from grid
            
        Returns:
            List of NC-schema compliant records
        """
        nc_records = []
        
        for idx, row in enumerate(raw_rows):
            try:
                # Extract fields from grid (case-insensitive matching)
                row_lower = {k.lower(): v for k, v in row.items()}
                
                # Helper to get value from row (flexible matching with synonyms)
                def get_field(field_candidates: List[str]) -> Optional[str]:
                    """
                    Find field value by checking if any candidate appears in any header.
                    Uses normalized contains matching.
                    """
                    for key in row.keys():
                        normalized_key = self._normalize_header(key)
                        for candidate in field_candidates:
                            candidate_norm = candidate.lower().strip()
                            if candidate_norm in normalized_key:
                                value = row[key]
                                return value if value else None
                    return None
                
                # Instrument number (required) - flexible matching
                instrument_number = get_field(["instrument", "inst", "doc", "document", "#", "number"])
                
                if not instrument_number:
                    self.logger.warning(f"Row {idx}: No instrument number found, skipping")
                    continue
                
                # Book and Page
                book = get_field(["book"])
                page = get_field(["page"])
                
                # Document type
                doc_type_original = get_field(["type", "doc type", "document type"])
                doc_type = doc_type_original.upper().strip() if doc_type_original else None
                
                # Parties (deterministic positional mapping)
                searched_name = get_field(["searched name", "name", "party 1"])
                cross_party_name = get_field(["cross party", "party 2"])
                
                # CRITICAL: Use null, not empty list when missing
                grantors = [searched_name.upper()] if searched_name else None
                grantees = [cross_party_name.upper()] if cross_party_name else None
                
                # Date
                filed_date = get_field(["filed", "date", "record date"])
                date_iso = self._parse_date_with_timezone(filed_date)
                
                # Build NC schema record
                nc_record = {
                    "instrument_number": instrument_number,
                    "parcel_number": None,  # Not available in grid
                    "county": "seminole",
                    "state": "FL",
                    "book": book,
                    "page": page,
                    "doc_type": doc_type,
                    "doc_category": None,  # Not available in grid
                    "original_doc_type": doc_type_original,
                    "book_type": None,  # Not available in grid
                    "grantors": grantors,
                    "grantees": grantees,
                    "date": date_iso,
                    "consideration": None,  # Not available in grid
                }
                
                nc_records.append(nc_record)
                
            except Exception as e:
                self.logger.error(f"Error transforming row {idx}: {e}")
                continue
        
        self.logger.info(f"Transformed {len(nc_records)} rows to NC schema")
        return nc_records
    
    def search_by_name(self, name: str) -> List[Dict[str, Any]]:
        """
        Search for records by person/entity name.
        
        Args:
            name: Person or entity name (e.g., "SMITH JOHN")
            
        Returns:
            List of NC-schema records (plain array)
        """
        self.logger.info(f"Starting search for: {name}")
        start_time = time.time()
        
        try:
            # Navigate to site with retries
            self.logger.info(f"Navigating to {self.BASE_URL}")
            self._with_retries("Navigate to BASE_URL", lambda: self.driver.get(self.BASE_URL))
            
            # Log page title for debugging
            self.logger.info(f"Page loaded: {self.driver.title}")
            
            # Accept disclaimer if present
            self._accept_disclaimer_if_present()
            
            # Ensure we're in default content before interacting with form
            self.driver.switch_to.default_content()
            
            # Wait for page to be fully loaded
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # 1) Set criteria direction to BOTH (use native click, not just JS property)
            try:
                direction_both = self.driver.find_element(By.ID, "criteria_direction_both")
                
                # Check if already selected
                is_checked = self.driver.execute_script("return arguments[0].checked;", direction_both)
                if not is_checked:
                    # Use native click to trigger proper event handlers
                    direction_both.click()
                    time.sleep(0.2)  # Let event handlers complete
                
                # Verify selection
                is_checked = self.driver.execute_script("return arguments[0].checked;", direction_both)
                self.logger.info(f"Set criteria direction to BOTH (checked={is_checked})")
            except Exception as e:
                self.logger.warning(f"Could not set criteria_direction_both: {e}")
            
            # 2) ENSURE name criteria checkbox is CHECKED (use native click)
            # This checkbox controls showing the searched name in results column
            try:
                name_direction_cb = self.driver.find_element(By.ID, "criteria_name_direction")
                initial_state = self.driver.execute_script("return arguments[0].checked;", name_direction_cb)
                
                # Ensure it's checked using native click (triggers proper handlers)
                if not initial_state:
                    name_direction_cb.click()
                    time.sleep(0.2)  # Let event handlers complete
                
                final_state = self.driver.execute_script("return arguments[0].checked;", name_direction_cb)
                self.logger.info(f"Name direction checkbox (#criteria_name_direction): checked={final_state}")
            except Exception as e:
                self.logger.warning(f"Could not set name direction checkbox: {e}")
            
            # Find and fill name input
            try:
                name_input = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                    EC.element_to_be_clickable((By.ID, "criteria_full_name"))
                )
            except TimeoutException:
                self.logger.error("Name input not found (id=criteria_full_name)")
                self._maybe_screenshot("name_input_not_found")
                raise TimeoutException("Could not find name input field (id=criteria_full_name)")
            
            # Scroll into view
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                name_input
            )
            time.sleep(0.2)
            
            # Fill name using native send_keys (triggers natural events)
            name_input.clear()
            time.sleep(0.2)  # Brief pause after clear
            
            name_input.send_keys(name)
            
            # Verify value was set
            entered_value = name_input.get_attribute("value")
            self.logger.info(f"Entered name: '{entered_value}'")
            
            # Trigger blur to ensure onChange handlers fire
            name_input.send_keys("\t")  # Tab away from field
            
            # CRITICAL: Wait for form to be fully ready before clicking SEARCH
            # The form needs time to process bindings/validation after input
            self.logger.info("Waiting for form to be ready...")
            time.sleep(2)  # Give form time to process input and update state
            
            # Find and click SEARCH button (scope to Search Criteria panel, handle <a> elements)
            try:
                # First, locate the Search Criteria container
                search_criteria_panel = self.driver.find_element(
                    By.XPATH,
                    "//*[contains(text(), 'Search Criteria') or contains(text(), 'search criteria')]"
                )
                
                # Find SEARCH control within that panel (support both <a> and <button>)
                # XPath: case-insensitive "search" in <a> or <button> with class 'btn'
                search_xpath = (
                    "./ancestor::*[1]/following-sibling::*//*["
                    "(self::a or self::button or self::input[@type='submit']) "
                    "and contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'search')"
                    "]"
                )
                
                search_button = WebDriverWait(self.driver, 10).until(
                    lambda d: search_criteria_panel.find_element(By.XPATH, search_xpath)
                )
                
                self.logger.info(f"Found SEARCH control: <{search_button.tag_name}> element")
                
                # Scroll into view and use JavaScript click (defensive)
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", search_button
                )
                time.sleep(0.3)
                
                # Click with JavaScript (bypasses overlay/intercept issues)
                self.driver.execute_script("arguments[0].click();", search_button)
                self.logger.info("Clicked SEARCH button (JS click)")
                
            except Exception as e:
                # Log detailed error
                self.logger.error(f"Failed to click SEARCH button: {type(e).__name__}: {e}")
                self.logger.error(f"URL: {self.driver.current_url}")
                self.logger.error(f"Title: {self.driver.title}")
                self._maybe_screenshot("search_click_error")
                raise
            
            # Wait for results with strong post-click synchronization
            has_results = self._wait_for_results()
            
            # 3) Name format fallback: if 0 results and name has no comma, try with comma
            if not has_results and "," not in name:
                # Try converting "LAST FIRST" -> "LAST, FIRST"
                parts = name.split(maxsplit=1)
                if len(parts) == 2:
                    name_with_comma = f"{parts[0]}, {parts[1]}"
                    self.logger.info(f"0 results with '{name}' - retrying with comma format: '{name_with_comma}'")
                    
                    try:
                        # Ensure in default content
                        self.driver.switch_to.default_content()
                        
                        # Re-locate and clear name input
                        name_input = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.ID, "criteria_full_name"))
                        )
                        
                        # Clear and enter with native send_keys
                        name_input.clear()
                        time.sleep(0.2)
                        name_input.send_keys(name_with_comma)
                        time.sleep(0.3)
                        name_input.send_keys("\t")  # Tab to trigger blur/change
                        
                        entered_value = name_input.get_attribute("value")
                        self.logger.info(f"Re-entered name: '{entered_value}'")
                        
                        # Re-locate SEARCH control with simpler, more reliable XPath
                        search_control = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((
                                By.XPATH,
                                "//*[(self::a or self::button) and contains(translate(normalize-space(.), "
                                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'search')]"
                            ))
                        )
                        
                        # Scroll and click with JavaScript
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                            search_control
                        )
                        self.logger.info("Re-clicked SEARCH control with comma format")
                        
                        # Wait for results again
                        has_results = self._wait_for_results()
                        
                        if has_results:
                            self.logger.info(f"✓ Comma format '{name_with_comma}' produced results!")
                        else:
                            self.logger.info(f"Comma format also returned 0 results")
                    
                    except Exception as e:
                        self.logger.warning(f"Comma format retry failed: {type(e).__name__}: {e}")
                        # Continue with no results (don't crash)
            
            if not has_results:
                duration = time.time() - start_time
                self.logger.info(
                    f"Search completed: 0 records found in {duration:.1f}s"
                )
                return []
            
            # Extract first page results
            all_rows = self._extract_page_results()
            
            # Handle pagination
            all_rows = self._handle_pagination(all_rows)
            
            # Transform to NC schema
            nc_records = self._transform_to_nc_schema(all_rows)
            
            duration = time.time() - start_time
            rpm = (len(nc_records) / duration * 60) if duration > 0 else 0
            
            self.logger.info(
                f"Search completed: {len(nc_records)} records in {duration:.1f}s "
                f"({rpm:.1f} records/min)"
            )
            
            return nc_records
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            raise


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_records(records: List[Dict[str, Any]], expected_count: Optional[int] = None) -> Dict[str, Any]:
    """
    Run all validations on a list of records.
    
    Args:
        records: List of NC-schema record dicts
        expected_count: Expected number of records (None to skip count validation)
        
    Returns:
        Validation results dict with boolean flags and errors list
    """
    errors = []
    actual_count = len(records)
    
    # 1) Count validation
    if expected_count is not None:
        count_match = (actual_count == expected_count)
        if not count_match:
            errors.append(f"Count mismatch: expected {expected_count}, got {actual_count}")
    else:
        count_match = True  # Skip if no expected count
    
    # 2) Schema validation - check each record has exact required keys
    schema_keys_ok = True
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            schema_keys_ok = False
            errors.append(f"Record {idx}: not a dict")
            continue
        record_keys = set(record.keys())
        if record_keys != NC_SCHEMA_KEYS:
            schema_keys_ok = False
            missing = NC_SCHEMA_KEYS - record_keys
            extra = record_keys - NC_SCHEMA_KEYS
            if missing:
                errors.append(f"Record {idx}: missing keys {missing}")
            if extra:
                errors.append(f"Record {idx}: extra keys {extra}")
    
    # 3) Null rules - certain fields must be None
    nulls_ok = True
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        for field in MUST_BE_NULL_FIELDS:
            if field in record and record[field] is not None:
                nulls_ok = False
                errors.append(f"Record {idx}: {field} should be None, got {record[field]!r}")
        # grantors/grantees: if missing data, must be None (not empty list)
        for party_field in ("grantors", "grantees"):
            val = record.get(party_field)
            if val is not None and not isinstance(val, list):
                nulls_ok = False
                errors.append(f"Record {idx}: {party_field} should be list or None, got {type(val).__name__}")
            if isinstance(val, list) and len(val) == 0:
                nulls_ok = False
                errors.append(f"Record {idx}: {party_field} is empty list (should be None if no data)")
    
    # 4) Uppercase rules - names in grantors/grantees must be uppercase
    uppercase_names_ok = True
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        for party_field in ("grantors", "grantees"):
            val = record.get(party_field)
            if isinstance(val, list):
                for name_idx, name in enumerate(val):
                    if isinstance(name, str) and name != name.upper():
                        uppercase_names_ok = False
                        errors.append(f"Record {idx}: {party_field}[{name_idx}] not uppercase: {name!r}")
    
    # 5) Date format rules - ISO 8601 with timezone offset
    date_timezone_ok = True
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        date_val = record.get("date")
        if date_val is not None:
            if not isinstance(date_val, str):
                date_timezone_ok = False
                errors.append(f"Record {idx}: date should be string, got {type(date_val).__name__}")
            elif "T" not in date_val:
                date_timezone_ok = False
                errors.append(f"Record {idx}: date missing 'T' separator: {date_val!r}")
            else:
                # Check for timezone offset (e.g., -05:00, +00:00, Z)
                has_tz = (
                    date_val.endswith("Z") or
                    re.search(r'[+-]\d{2}:\d{2}$', date_val) is not None
                )
                if not has_tz:
                    date_timezone_ok = False
                    errors.append(f"Record {idx}: date missing timezone offset: {date_val!r}")
    
    # 6) No-link rule - no URLs in any string field
    no_links_ok = True
    string_fields = ["instrument_number", "book", "page", "doc_type", "original_doc_type", "date"]
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        # Check direct string fields
        for field in string_fields:
            val = record.get(field)
            if isinstance(val, str) and ("http://" in val.lower() or "https://" in val.lower()):
                no_links_ok = False
                errors.append(f"Record {idx}: {field} contains URL: {val!r}")
        # Check party name lists
        for party_field in ("grantors", "grantees"):
            val = record.get(party_field)
            if isinstance(val, list):
                for name in val:
                    if isinstance(name, str) and ("http://" in name.lower() or "https://" in name.lower()):
                        no_links_ok = False
                        errors.append(f"Record {idx}: {party_field} contains URL: {name!r}")
    
    return {
        "count_match": count_match,
        "schema_keys_ok": schema_keys_ok,
        "nulls_ok": nulls_ok,
        "uppercase_names_ok": uppercase_names_ok,
        "date_timezone_ok": date_timezone_ok,
        "no_links_ok": no_links_ok,
        "errors": errors
    }


def is_test_passed(validations: Dict[str, Any]) -> bool:
    """Check if all validations passed (all booleans True and no errors)."""
    return (
        validations["count_match"] and
        validations["schema_keys_ok"] and
        validations["nulls_ok"] and
        validations["uppercase_names_ok"] and
        validations["date_timezone_ok"] and
        validations["no_links_ok"] and
        len(validations["errors"]) == 0
    )


def run_test_suite(scraper: SeminoleScraper, logger: logging.Logger) -> Dict[str, Any]:
    """
    Run all test cases and return structured results.
    
    Args:
        scraper: Initialized SeminoleScraper instance (reused across tests)
        logger: Logger for output
        
    Returns:
        Test results dict ready for JSON serialization
    """
    et_tz = pytz.timezone("America/New_York")
    generated_at = datetime.now(et_tz).isoformat()
    
    tests_results = []
    passed_count = 0
    failed_count = 0
    
    for idx, test_case in enumerate(TEST_CASES):
        test_name = test_case["name"]
        expected_count = test_case["expected_count"]
        
        logger.info(f"=" * 60)
        logger.info(f"TEST {idx + 1}/{len(TEST_CASES)}: '{test_name}' (expected: {expected_count} records)")
        logger.info(f"=" * 60)
        
        try:
            # Run the search
            records = scraper.search_by_name(test_name)
            actual_count = len(records)
            
            # Run validations
            validations = validate_records(records, expected_count)
            
            # Determine pass/fail
            passed = is_test_passed(validations)
            if passed:
                passed_count += 1
                logger.info(f"✓ TEST PASSED: '{test_name}' - {actual_count} records")
            else:
                failed_count += 1
                logger.warning(f"✗ TEST FAILED: '{test_name}' - {actual_count} records")
                for err in validations["errors"][:5]:  # Log first 5 errors
                    logger.warning(f"  - {err}")
                if len(validations["errors"]) > 5:
                    logger.warning(f"  ... and {len(validations['errors']) - 5} more errors")
            
            tests_results.append({
                "name": test_name,
                "expected_count": expected_count,
                "actual_count": actual_count,
                "validations": validations,
                "records": records
            })
            
        except Exception as e:
            # Test failed due to exception
            failed_count += 1
            logger.error(f"✗ TEST EXCEPTION: '{test_name}' - {type(e).__name__}: {e}")
            
            tests_results.append({
                "name": test_name,
                "expected_count": expected_count,
                "actual_count": 0,
                "validations": {
                    "count_match": False,
                    "schema_keys_ok": False,
                    "nulls_ok": False,
                    "uppercase_names_ok": False,
                    "date_timezone_ok": False,
                    "no_links_ok": False,
                    "errors": [f"Exception: {type(e).__name__}: {e}"]
                },
                "records": []
            })
        
        # Delay between tests (respectful to server)
        if idx < len(TEST_CASES) - 1:
            logger.info("Waiting 2 seconds before next test...")
            time.sleep(2)
    
    logger.info(f"=" * 60)
    logger.info(f"TEST SUITE COMPLETE: {passed_count} passed, {failed_count} failed")
    logger.info(f"=" * 60)
    
    return {
        "generated_at": generated_at,
        "county": "seminole",
        "state": "FL",
        "tests": tests_results,
        "summary": {
            "passed": passed_count,
            "failed": failed_count
        }
    }


def run_single_search(scraper: SeminoleScraper, name: str, logger: logging.Logger) -> Dict[str, Any]:
    """
    Run a single search and return structured results (same format as test suite).
    
    Args:
        scraper: Initialized SeminoleScraper instance
        name: Name to search
        logger: Logger for output
        
    Returns:
        Test results dict ready for JSON serialization
    """
    et_tz = pytz.timezone("America/New_York")
    generated_at = datetime.now(et_tz).isoformat()
    
    try:
        records = scraper.search_by_name(name)
        actual_count = len(records)
        
        # Run validations (no expected count for ad-hoc searches)
        validations = validate_records(records, expected_count=None)
        
        passed = is_test_passed(validations)
        
        return {
            "generated_at": generated_at,
            "county": "seminole",
            "state": "FL",
            "tests": [{
                "name": name,
                "expected_count": None,
                "actual_count": actual_count,
                "validations": validations,
                "records": records
            }],
            "summary": {
                "passed": 1 if passed else 0,
                "failed": 0 if passed else 1
            }
        }
        
    except Exception as e:
        logger.error(f"Search failed: {type(e).__name__}: {e}")
        return {
            "generated_at": generated_at,
            "county": "seminole",
            "state": "FL",
            "tests": [{
                "name": name,
                "expected_count": None,
                "actual_count": 0,
                "validations": {
                    "count_match": True,  # N/A for single search
                    "schema_keys_ok": False,
                    "nulls_ok": False,
                    "uppercase_names_ok": False,
                    "date_timezone_ok": False,
                    "no_links_ok": False,
                    "errors": [f"Exception: {type(e).__name__}: {e}"]
                },
                "records": []
            }],
            "summary": {
                "passed": 0,
                "failed": 1
            }
        }


def main():
    """Command-line interface for Seminole County scraper."""
    parser = argparse.ArgumentParser(
        description="Scrape Seminole County FL official records"
    )
    parser.add_argument(
        "--name",
        help="Name to search (e.g., 'SMITH JOHN'). Ignored if --run-tests is used."
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        dest="run_tests",
        help="Run the predefined test suite (3 test cases) instead of a single search"
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help="(ignored) Output always written to outputs/seminole_test_results.json"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.run_tests and not args.name:
        parser.error("Either --name or --run-tests is required")
    
    # Always use fixed output path (assignment requirement)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize scraper (reused across all tests/searches)
    scraper = SeminoleScraper(headless=args.headless)
    logger = scraper.logger
    
    try:
        if args.run_tests:
            # Run the full test suite
            logger.info("Starting test suite with 3 predefined test cases...")
            results = run_test_suite(scraper, logger)
            
            # Summary for console
            summary = results["summary"]
            total_records = sum(t["actual_count"] for t in results["tests"])
            
            if summary["failed"] == 0:
                print(f"\n✅ TEST SUITE PASSED: {summary['passed']}/{summary['passed']} tests, {total_records} total records")
            else:
                print(f"\n⚠️ TEST SUITE: {summary['passed']} passed, {summary['failed']} failed, {total_records} total records")
        else:
            # Run single search
            logger.info(f"Running single search for: {args.name}")
            results = run_single_search(scraper, args.name, logger)
            
            # Summary for console
            test_result = results["tests"][0]
            actual_count = test_result["actual_count"]
            validations = test_result["validations"]
            
            if is_test_passed(validations):
                print(f"\n✅ Success: {actual_count} records (all validations passed)")
            else:
                error_count = len(validations["errors"])
                print(f"\n⚠️ Completed: {actual_count} records ({error_count} validation warnings)")
        
        # Write results to fixed output path
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"📁 Results saved to {OUTPUT_PATH}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    finally:
        scraper.close()


if __name__ == "__main__":
    main()

