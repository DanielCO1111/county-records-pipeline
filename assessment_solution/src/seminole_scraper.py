"""
Seminole County FL Official Records Scraper

This module scrapes official records from Seminole County, FL and converts them
to the North Carolina schema format for system compatibility.

Website: https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html
"""

import argparse
import json
import logging
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
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService


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
                
                # Save screenshot
                screenshot_path = Path("outputs") / f"disclaimer_error_{int(time.time())}.png"
                screenshot_path.parent.mkdir(exist_ok=True)
                self.driver.save_screenshot(str(screenshot_path))
                self.logger.error(f"Screenshot saved: {screenshot_path}")
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
            self.logger.error("Timeout waiting for igGrid pager label")
            
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
            
            # Save screenshot
            screenshot_path = Path("outputs") / f"pager_timeout_{int(time.time())}.png"
            screenshot_path.parent.mkdir(exist_ok=True)
            self.driver.save_screenshot(str(screenshot_path))
            self.logger.error(f"Screenshot saved: {screenshot_path}")
            
            return False
        
        except Exception as e:
            self.logger.error(f"Error waiting for igGrid: {type(e).__name__}: {e}")
            return False
            
        except TimeoutException:
            self.logger.error("Timeout waiting for igGrid results")
            
            # Debug info
            try:
                record_count = self.driver.find_elements(By.XPATH, 
                    "//*[contains(text(), 'record') or contains(text(), 'Record')]")
                record_text = record_count[0].text if record_count else "N/A"
                self.logger.error(f"Record count text: {record_text}")
                self.logger.error(f"URL: {self.driver.current_url}")
                self.logger.error(f"Title: {self.driver.title}")
            except Exception:
                pass
            
            # Save screenshot
            screenshot_path = Path("outputs") / f"iggrid_timeout_{int(time.time())}.png"
            screenshot_path.parent.mkdir(exist_ok=True)
            self.driver.save_screenshot(str(screenshot_path))
            self.logger.error(f"Screenshot saved: {screenshot_path}")
            
            return False
        
        except Exception as e:
            self.logger.error(f"Error waiting for igGrid: {type(e).__name__}: {e}")
            return False
    
    def _get_pagination_info(self) -> tuple[int, int]:
        """
        Extract current page and total pages from pagination footer.
        
        Returns:
            (current_page, total_pages) tuple
        """
        try:
            # Look for "Pg X of Y" or similar text
            footer_elements = self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(), 'Pg') or contains(text(), 'Page')]"
            )
            
            for elem in footer_elements:
                text = elem.text
                # Parse "Pg 1 of 10" or "Page 1 of 10"
                if " of " in text:
                    parts = text.split(" of ")
                    if len(parts) == 2:
                        current_str = parts[0].split()[-1]  # Get last word (the number)
                        total_str = parts[1].split()[0]  # Get first word (the number)
                        return int(current_str), int(total_str)
            
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
                            screenshot_path = Path("outputs") / f"extraction_mismatch_{int(time.time())}.png"
                            screenshot_path.parent.mkdir(exist_ok=True)
                            self.driver.save_screenshot(str(screenshot_path))
                            self.logger.warning(f"Screenshot saved: {screenshot_path}")
                except Exception:
                    pass
            
        except Exception as e:
            self.logger.error(f"Error in igGrid extraction: {type(e).__name__}: {e}")
        
        return rows_data
    
    def _click_next_page(self) -> bool:
        """
        Click the 'Next' button to navigate to next page.
        
        Returns:
            True if successfully clicked, False if button disabled/not found
        """
        try:
            # Try multiple selectors for Next button
            selectors = [
                (By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'next')]"),
                (By.XPATH, "//a[contains(text(), 'Next') or contains(text(), 'next')]"),
                (By.CSS_SELECTOR, "button.next"),
                (By.CSS_SELECTOR, "a.next"),
            ]
            
            next_button = None
            for by, selector in selectors:
                try:
                    next_button = self.driver.find_element(by, selector)
                    if next_button:
                        break
                except NoSuchElementException:
                    continue
            
            if not next_button:
                self.logger.info("Next button not found")
                return False
            
            # Check if disabled
            if "disabled" in next_button.get_attribute("class") or not next_button.is_enabled():
                self.logger.info("Next button is disabled (last page)")
                return False
            
            # Get first row's instrument number before clicking (for wait condition)
            first_row_instrument = None
            try:
                first_row = self.driver.find_element(By.CSS_SELECTOR, "table tbody tr:first-child")
                first_cell = first_row.find_element(By.TAG_NAME, "td")
                first_row_instrument = first_cell.text.strip()
            except Exception:
                pass
            
            # Click Next
            next_button.click()
            self.logger.info("Clicked Next button")
            
            # Wait for page change (first row instrument number changes)
            if first_row_instrument:
                try:
                    WebDriverWait(self.driver, self.PAGE_TIMEOUT).until(
                        lambda d: (
                            d.find_element(By.CSS_SELECTOR, "table tbody tr:first-child td").text.strip()
                            != first_row_instrument
                        )
                    )
                    self.logger.debug("Page content changed (row data updated)")
                except TimeoutException:
                    self.logger.warning("Timeout waiting for page change - continuing anyway")
            
            # Respectful delay
            time.sleep(self.REQUEST_DELAY)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error clicking next page: {e}")
            return False
    
    def _handle_pagination(self, all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Handle pagination and collect all results across multiple pages.
        
        Args:
            all_rows: Initial rows from first page
            
        Returns:
            Complete list of all rows from all pages
        """
        start_time = time.time()
        current_page = 1
        
        while True:
            # Check total runtime limit
            if time.time() - start_time > self.TOTAL_RUNTIME_LIMIT:
                self.logger.error(
                    f"Hit maximum runtime of {self.TOTAL_RUNTIME_LIMIT}s after {current_page} pages"
                )
                break
            
            # Get pagination info
            current_page_num, total_pages = self._get_pagination_info()
            self.logger.info(f"On page {current_page_num} of {total_pages}")
            
            # Check if we're on the last page
            if current_page_num >= total_pages:
                self.logger.info(f"Reached last page ({current_page_num} of {total_pages})")
                break
            
            # Try to click Next
            if not self._click_next_page():
                self.logger.info("Could not navigate to next page - ending pagination")
                break
            
            current_page += 1
            
            # Extract rows from new page
            try:
                page_rows = self._extract_page_results()
                all_rows.extend(page_rows)
                self.logger.info(
                    f"Page {current_page}: collected {len(page_rows)} rows "
                    f"(total: {len(all_rows)})"
                )
            except TimeoutException:
                self.logger.error(f"Page {current_page} timed out - stopping pagination")
                break
            except Exception as e:
                self.logger.error(f"Error on page {current_page}: {e}")
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
                # Debug: save screenshot
                screenshot_path = Path("outputs") / f"name_input_not_found_{int(time.time())}.png"
                screenshot_path.parent.mkdir(exist_ok=True)
                self.driver.save_screenshot(str(screenshot_path))
                self.logger.error(f"Name input not found. Screenshot: {screenshot_path}")
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
                # Log detailed error and save screenshot
                self.logger.error(f"Failed to click SEARCH button: {type(e).__name__}: {e}")
                self.logger.error(f"URL: {self.driver.current_url}")
                self.logger.error(f"Title: {self.driver.title}")
                
                screenshot_path = Path("outputs") / f"search_click_error_{int(time.time())}.png"
                screenshot_path.parent.mkdir(exist_ok=True)
                self.driver.save_screenshot(str(screenshot_path))
                self.logger.error(f"Screenshot saved: {screenshot_path}")
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


def main():
    """Command-line interface for Seminole County scraper."""
    parser = argparse.ArgumentParser(
        description="Scrape Seminole County FL official records"
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Name to search (e.g., 'SMITH JOHN')"
    )
    parser.add_argument(
        "--output",
        default="outputs/seminole_test_results.json",
        help="Output JSON file path"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Run scraper
    scraper = SeminoleScraper(headless=args.headless)
    
    try:
        records = scraper.search_by_name(args.name)
        
        # Write plain JSON array (NO metadata wrapper)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Success: {len(records)} records saved to {output_path}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    finally:
        scraper.close()


if __name__ == "__main__":
    main()

