"""
Seminole County FL Official Records Scraper

This module scrapes official records from Seminole County, FL and converts them
to the North Carolina schema format for system compatibility.

Website: https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html
"""

import argparse
import json
import logging
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
        """Configure logging with appropriate format."""
        logger = logging.getLogger("SeminoleScraper")
        logger.setLevel(logging.INFO)
        
        # Console handler
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
    
    def _accept_disclaimer_if_present(self):
        """
        Click 'AGREED & ENTER' button if present (disclaimer gate).
        
        This is idempotent - if button is not present, it proceeds.
        """
        try:
            # Use XPath contains() for robust matching
            button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(text(), 'AGREED') and contains(text(), 'ENTER')]"
                ))
            )
            button.click()
            self.logger.info("Clicked 'AGREED & ENTER' button")
            
            # Wait for search form to be present
            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Name')]"))
            )
            self.logger.info("Search form loaded")
            
        except TimeoutException:
            # Button not present - already past disclaimer or different flow
            self.logger.info("No disclaimer button found - proceeding")
        except Exception as e:
            self.logger.warning(f"Error handling disclaimer: {e}")
    
    def _wait_for_results(self) -> bool:
        """
        Wait for search results grid to load (grid-first strategy).
        
        Returns:
            True if results present, False if no results
        """
        try:
            # Wait for either results grid or "no results" message
            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                lambda d: (
                    len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0
                    or len(d.find_elements(By.XPATH, "//*[contains(text(), 'No records')]")) > 0
                    or len(d.find_elements(By.XPATH, "//*[contains(text(), 'no results')]")) > 0
                )
            )
            
            # Check if we have results or "no results" message
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            no_results = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No records') or contains(text(), 'no results')]")
            
            if no_results or len(rows) == 0:
                self.logger.info("No results found")
                return False
            
            self.logger.info(f"Results grid loaded with {len(rows)} rows visible")
            
            # Best-effort: wait for spinner to disappear
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.invisibility_of_element_located((By.CLASS_NAME, "loading-spinner"))
                )
            except TimeoutException:
                self.logger.debug("Spinner check timed out (grid is present, continuing)")
            
            return True
            
        except TimeoutException:
            self.logger.warning("Timeout waiting for results grid")
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
    
    def _extract_page_results(self) -> List[Dict[str, Any]]:
        """
        Extract all rows from the current page's results grid.
        
        Returns:
            List of raw row data dictionaries
        """
        rows_data = []
        
        try:
            # Find all data rows in table
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            
            # Get column headers to map indices
            headers = []
            try:
                header_cells = self.driver.find_elements(By.CSS_SELECTOR, "table thead th")
                headers = [cell.text.strip() for cell in header_cells]
                self.logger.debug(f"Grid headers: {headers}")
            except Exception as e:
                self.logger.warning(f"Could not extract headers: {e}")
            
            for row_idx, row in enumerate(rows):
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) == 0:
                        continue
                    
                    # Extract cell values
                    cell_values = [cell.text.strip() for cell in cells]
                    
                    # Map to column names (if headers available)
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
                    
                except Exception as e:
                    self.logger.warning(f"Error extracting row {row_idx}: {e}")
                    continue
            
            self.logger.info(f"Extracted {len(rows_data)} rows from current page")
            
        except Exception as e:
            self.logger.error(f"Error extracting page results: {e}")
        
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
                
                # Helper to get value from row (case-insensitive)
                def get_field(field_name: str) -> Optional[str]:
                    for key in row.keys():
                        if key.lower() == field_name.lower():
                            value = row[key]
                            return value if value else None
                    return None
                
                # Instrument number (required)
                instrument_number = (
                    get_field("Instrument #") or
                    get_field("Instrument") or
                    get_field("Instrument Number") or
                    get_field("Document #") or
                    get_field("Document Number")
                )
                
                if not instrument_number:
                    self.logger.warning(f"Row {idx}: No instrument number found, skipping")
                    continue
                
                # Book and Page
                book = get_field("Book")
                page = get_field("Page")
                
                # Document type
                doc_type_original = (
                    get_field("Type") or
                    get_field("Doc Type") or
                    get_field("Document Type")
                )
                doc_type = doc_type_original.upper().strip() if doc_type_original else None
                
                # Parties (deterministic positional mapping)
                searched_name = (
                    get_field("Searched Name") or
                    get_field("Name") or
                    get_field("Party 1")
                )
                cross_party_name = (
                    get_field("Cross Party Name") or
                    get_field("Cross Party") or
                    get_field("Party 2")
                )
                
                # CRITICAL: Use null, not empty list when missing
                grantors = [searched_name.upper()] if searched_name else None
                grantees = [cross_party_name.upper()] if cross_party_name else None
                
                # Date
                filed_date = (
                    get_field("Filed") or
                    get_field("Date") or
                    get_field("Record Date")
                )
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
            # Navigate to site
            self.logger.info(f"Navigating to {self.BASE_URL}")
            self.driver.get(self.BASE_URL)
            
            # Accept disclaimer if present
            self._accept_disclaimer_if_present()
            
            # Find and fill name input
            name_input = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//input[contains(@placeholder, 'Name') or contains(@placeholder, 'name')]"
                ))
            )
            name_input.clear()
            name_input.send_keys(name)
            self.logger.info(f"Entered name: {name}")
            
            # Find and click Search button
            search_button = self.driver.find_element(
                By.XPATH,
                "//button[contains(text(), 'Search') or contains(text(), 'SEARCH')]"
            )
            search_button.click()
            self.logger.info("Clicked Search button")
            
            # Wait for results
            has_results = self._wait_for_results()
            
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

