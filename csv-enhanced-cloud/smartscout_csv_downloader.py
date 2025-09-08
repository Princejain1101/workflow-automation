"""
This script automates the generation and saving of a brand report from SmartScout.

After searching for a brand, it waits for the report analysis to complete and then
saves the entire report page as a local HTML file.

It is designed to be used with a browser that is already logged into SmartScout.
The script will connect to a persistent browser context, which means you need to
log in manually just once.

**Prerequisites:**
1. Python 3.7+ installed.
2. Required packages installed:
   pip install playwright beautifulsoup4 anthropic pdfplumber pytesseract pdf2image
   playwright install
3. Anthropic API key set as environment variable:
   export ANTHROPIC_API_KEY="your-api-key-here"

**How to run the script:**
1. **First-time setup (to log in):**
   - Run the script with the `--setup` argument: `python smartscout_downloader.py --setup`
   - This will open a browser window. Log into your SmartScout account as you normally would.
   - Once you are logged in, you can close the browser. The script will have saved your session.

2. **Running the automation:**
   - After the first-time setup, you can run the script to generate and save a report.
   - You will need to provide the name of the brand for the report.
   - The script will save the report as an HTML file and generate an AI summary.
   - Output files: 'brand_name_report.html' and 'brand_name_summary.txt'
   - Example: `python smartscout_downloader.py "Example Brand Name"`
"""
import os
import sys
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, expect
from bs4 import BeautifulSoup

# --- Configuration ---
# The directory where your browser session data will be stored.
# This allows you to stay logged in between runs.
USER_DATA_DIR = "./playwright_user_data"
SMARTSCOUT_URL = "https://app.smartscout.com/app/tailored-report"
SMARTSCOUT_API_BASE = "https://api.smartscout.com"

# API Authentication - check for API key
SMARTSCOUT_API_KEY = os.getenv('SMARTSCOUT_API_KEY')
if not SMARTSCOUT_API_KEY:
    # Try to load from config file
    config_file = os.path.expanduser('~/.smartscout_config.json')
    if os.path.exists(config_file):
        try:
            import json
            with open(config_file, 'r') as f:
                config = json.load(f)
                SMARTSCOUT_API_KEY = config.get('api_key')
        except:
            pass

def get_brand_data_via_api(brand_name: str, marketplace: str = "US"):
    """
    Fetch brand data using SmartScout API instead of web scraping.
    Requires SMARTSCOUT_API_KEY to be set.
    """
    if not SMARTSCOUT_API_KEY:
        return None
        
    try:
        import requests
        
        headers = {
            'X-Api-Key': SMARTSCOUT_API_KEY,
            'Content-Type': 'application/json'
        }
        
        # Search for the brand first
        search_url = f"{SMARTSCOUT_API_BASE}/brands/search"
        params = {
            'marketplace': marketplace,
            'query': brand_name,
            'limit': 10
        }
        
        print(f"🔍 Searching for '{brand_name}' via SmartScout API...")
        response = requests.get(search_url, headers=headers, params=params)
        
        if response.status_code == 200:
            search_data = response.json()
            brands = search_data.get('data', [])
            
            if brands:
                # Find exact match or closest match
                brand_match = None
                for brand in brands:
                    if brand.get('name', '').lower() == brand_name.lower():
                        brand_match = brand
                        break
                
                if not brand_match:
                    brand_match = brands[0]  # Take first result
                    
                brand_id = brand_match.get('id')
                if brand_id:
                    # Get detailed brand data
                    detail_url = f"{SMARTSCOUT_API_BASE}/brands/{brand_id}"
                    detail_params = {'marketplace': marketplace}
                    
                    print(f"📊 Fetching detailed data for brand ID: {brand_id}")
                    detail_response = requests.get(detail_url, headers=headers, params=detail_params)
                    
                    if detail_response.status_code == 200:
                        return detail_response.json()
                    else:
                        print(f"❌ API Error fetching brand details: {detail_response.status_code}")
                        return None
            else:
                print(f"❌ Brand '{brand_name}' not found in SmartScout API")
                return None
        else:
            print(f"❌ API Error searching for brand: {response.status_code}")
            return None
            
    except ImportError:
        print("❌ 'requests' library required for API access. Install with: pip install requests")
        return None
    except Exception as e:
        print(f"❌ API Error: {str(e)}")
        return None

def setup_api_key():
    """
    Interactive setup for SmartScout API key.
    """
    print("\n🔑 SmartScout API Key Setup")
    print("=" * 50)
    print("To use SmartScout API instead of browser automation:")
    print("1. Contact SmartScout support to get your API key")
    print("2. Visit: https://www.smartscout.com/contact")
    print("3. Request API access for your account")
    print("\nOnce you have your API key, you can set it up in two ways:")
    print("\n📁 Option 1: Environment Variable")
    print("   export SMARTSCOUT_API_KEY='your-api-key-here'")
    print("\n📄 Option 2: Config File")
    print("   Create ~/.smartscout_config.json with:")
    print('   {"api_key": "your-api-key-here"}')
    
    api_key = input("\n🔑 Enter your API key now (or press Enter to skip): ").strip()
    
    if api_key:
        config_file = os.path.expanduser('~/.smartscout_config.json')
        try:
            import json
            config = {"api_key": api_key}
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"✅ API key saved to {config_file}")
            print("🔄 Restart the script to use API authentication")
            return True
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            return False
    else:
        print("⏭️  Skipping API setup - will use browser automation")
        return False

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text content from PDF file using OCR for image-based PDFs.
    """
    try:
        import pdfplumber
        
        text_content = ""
        
        # First try regular text extraction
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content += page_text + "\n"
        
        # If no text found, try OCR approach
        if not text_content.strip():
            print("📸 PDF appears to be image-based, attempting OCR...")
            try:
                import pytesseract
                from pdf2image import convert_from_path
                
                # Convert PDF pages to images
                images = convert_from_path(pdf_path)
                
                for i, image in enumerate(images):
                    print(f"🔍 Processing page {i+1} with OCR...")
                    # Extract text from image using OCR
                    page_text = pytesseract.image_to_string(image)
                    if page_text:
                        text_content += page_text + "\n"
                
                print(f"✓ OCR completed on {len(images)} pages")
                
            except ImportError:
                return "❌ OCR libraries not installed. Please install with: pip install pytesseract pdf2image"
            except Exception as e:
                return f"❌ Error with OCR extraction: {str(e)}"
        
        return text_content if text_content.strip() else "❌ No text could be extracted from PDF"
        
    except ImportError:
        return "❌ pdfplumber library not installed. Please install with: pip install pdfplumber"
    except Exception as e:
        return f"❌ Error extracting PDF content: {str(e)}"

def extract_smartscout_data_from_dom(page_data: dict) -> dict:
    """
    Pass HTML content through to LLM for intelligent parsing.
    """
    # Simply return the HTML content for LLM processing
    if 'html_content' in page_data:
        print("✅ Passing HTML content to LLM for extraction")
        return {
            'html_content': page_data['html_content'],
            'content_length': page_data['content_length'],
            'extraction_method': 'html_for_llm'
        }
    
    # Legacy fallback - check if we have enhanced extracted data
    if 'extracted_metrics' in page_data:
        enhanced_data = page_data['extracted_metrics']
        
        # Convert to the expected format for the LLM analysis
        enhanced_result = {
            'sales_rank': enhanced_data.get('sales_rank'),
            'monthly_revenue': enhanced_data.get('monthly_revenue'),
            'revenue_change': enhanced_data.get('revenue_change'),
            'top_search_terms': enhanced_data.get('top_search_terms', []),
            'competing_asins': enhanced_data.get('competing_asins', []),
            'search_term_comparison': enhanced_data.get('search_term_comparison', {}),
            'keyword_distribution': enhanced_data.get('keyword_distribution', []),
            'all_revenue_figures': enhanced_data.get('all_revenue_figures', []),
            'all_percentages': enhanced_data.get('all_percentages', []),
            'full_text_length': len(page_data.get('full_text', ''))
        }
        
        print("✅ Using enhanced DOM extraction data")
        return enhanced_result
    
    # Fallback to legacy extraction
    print("⚠ Using legacy DOM extraction - consider updating to enhanced version")
    import re
    
    data = {
        'weekly_revenue': None,
        'revenue_change': None,
        'market_categories': [],
        'brand_data': [],
        'product_data': [],
        'asin_data': [],
        'search_terms': [],
        'keyword_metrics': {},
        'competitor_data': {},
        'all_revenue_figures': [],
        'all_percentages': []
    }
    
    # Process revenue elements
    if 'revenue_elements' in page_data:
        data['all_revenue_figures'] = page_data['revenue_elements']
        
        # Try to find weekly/monthly revenue
        for revenue in page_data['revenue_elements']:
            # Clean and extract dollar amounts
            dollar_match = re.search(r'\$[\d,]+(?:\.\d{2})?', revenue)
            if dollar_match and not data['weekly_revenue']:
                data['weekly_revenue'] = dollar_match.group()
    
    # Process percentage elements
    if 'percentage_elements' in page_data:
        data['all_percentages'] = page_data['percentage_elements']
        
        # Look for growth/change indicators
        for percent in page_data['percentage_elements']:
            if any(word in percent.lower() for word in ['growth', 'change', 'up', 'down']):
                if not data['revenue_change']:
                    data['revenue_change'] = percent
    
    # Process ASIN data
    if 'asin_elements' in page_data:
        for asin in page_data['asin_elements']:
            data['asin_data'].append({
                'asin': asin,
                'title': 'Unknown',  # Would need additional DOM extraction
                'sales_rank': None,
                'monthly_revenue': None,
                'revenue_change': None
            })
    
    # Process report text for additional patterns
    if 'report_text' in page_data:
        text = page_data['report_text']
        
        # Extract search terms from the text
        search_term_pattern = r'"([^"]+)"\s*\(?#?(\d+)(?:,\s*([\d,]+)\s*searches?)?\)?'
        search_matches = re.findall(search_term_pattern, text, re.IGNORECASE)
        for match in search_matches:
            data['search_terms'].append({
                'term': match[0],
                'rank': f"#{match[1]}" if match[1] else None,
                'searches': match[2] if match[2] else None
            })
        
        # Extract brand data from tables in the text
        brand_pattern = r'([A-Z][A-Z\s&]+)\s+([\d.]+%)\s+([+-]?[\d.]+%)'
        brand_matches = re.findall(brand_pattern, text, re.MULTILINE)
        for match in brand_matches:
            data['brand_data'].append({
                'brand': match[0].strip(),
                'share': match[1],
                'change': match[2]
            })
        
        # Extract keyword metrics
        keyword_metrics_pattern = r'(Unique Keywords|Organic Win Rate|Sponsored Win Rate|Shared Keywords)\s*:?\s*([\d,]+|[\d.]+%)'
        keyword_matches = re.findall(keyword_metrics_pattern, text, re.IGNORECASE)
        for match in keyword_matches:
            data['keyword_metrics'][match[0]] = match[1]
    
    return data

def extract_smartscout_data(text_content: str) -> dict:
    """
    Extract specific SmartScout data structures from text content.
    """
    import re
    
    data = {
        'weekly_revenue': None,
        'revenue_change': None,
        'market_categories': [],
        'brand_data': [],
        'product_data': [],
        'asin_data': [],
        'search_terms': [],
        'keyword_metrics': {},
        'competitor_data': {}
    }
    
    # Weekly Revenue pattern
    weekly_rev_pattern = r'Weekly Revenue:?\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:.*?([+-]?\$?[\d,]+(?:\.\d{2})?)\s*or\s*([+-]?[\d.]+%)|.*?([+-][\d.]+%))?'
    match = re.search(weekly_rev_pattern, text_content, re.IGNORECASE | re.DOTALL)
    if match:
        data['weekly_revenue'] = f"${match.group(1)}"
        if match.group(2):
            data['revenue_change'] = f"{match.group(2)} or {match.group(3)}" if match.group(3) else match.group(4)
    
    # ASIN data extraction
    asin_pattern = r'ASIN:?\s*([A-Z0-9]{10})\s*.*?Title:?\s*([^\n]+).*?(?:Sales Rank:?\s*#?([\d,]+))?.*?(?:Monthly Revenue:?\s*\$?([\d,]+(?:\.\d{2})?))?.*?(?:([+-]?[\d.]+%))?'
    asin_matches = re.findall(asin_pattern, text_content, re.IGNORECASE | re.DOTALL)
    for match in asin_matches:
        asin_data = {
            'asin': match[0],
            'title': match[1].strip(),
            'sales_rank': f"#{match[2]}" if match[2] else None,
            'monthly_revenue': f"${match[3]}" if match[3] else None,
            'revenue_change': match[4] if match[4] else None
        }
        data['asin_data'].append(asin_data)
    
    # Search terms extraction
    search_term_pattern = r'"([^"]+)"\s*\(#?(\d+),?\s*([\d,]+)\s*searches?\)'
    search_matches = re.findall(search_term_pattern, text_content, re.IGNORECASE)
    for match in search_matches:
        data['search_terms'].append({
            'term': match[0],
            'rank': f"#{match[1]}",
            'searches': match[2]
        })
    
    # Brand market share data
    brand_pattern = r'([A-Z][A-Z\s&]+)\s+([\d.]+%)\s+([+-]?[\d.]+%)'
    brand_matches = re.findall(brand_pattern, text_content, re.MULTILINE)
    for match in brand_matches:
        data['brand_data'].append({
            'brand': match[0].strip(),
            'share': match[1],
            'change': match[2]
        })
    
    # Category market share
    category_pattern = r'([A-Z][a-z\s]+)\s+([\d.]+%)\s+([+-]?[\d.]+%)'
    category_matches = re.findall(category_pattern, text_content, re.MULTILINE)
    for match in category_matches:
        if match[0].strip() not in [b['brand'] for b in data['brand_data']]:
            data['market_categories'].append({
                'category': match[0].strip(),
                'share': match[1],
                'change': match[2]
            })
    
    # Keyword metrics
    keyword_metrics_pattern = r'(Unique Keywords|Organic Win Rate|Sponsored Win Rate|Shared Keywords)\s+([\d,]+|[\d.]+%)'
    keyword_matches = re.findall(keyword_metrics_pattern, text_content, re.IGNORECASE)
    for match in keyword_matches:
        data['keyword_metrics'][match[0]] = match[1]
    
    # Revenue numbers (general)
    revenue_pattern = r'\$[\d,]+(?:\.\d{2})?'
    revenue_matches = re.findall(revenue_pattern, text_content)
    data['all_revenue_figures'] = list(set(revenue_matches))[:10]  # Top 10 unique
    
    # Percentage changes (general)
    percent_pattern = r'[+-]?[\d.]+%'
    percent_matches = re.findall(percent_pattern, text_content)
    data['all_percentages'] = list(set(percent_matches))[:15]  # Top 15 unique
    
    return data

def extract_metrics_from_pdf(pdf_path: str) -> dict:
    """
    Extract specific metrics from PDF file.
    """
    try:
        import pdfplumber
        import re
        
        metrics = {
            'revenue_data': [],
            'growth_data': [],
            'rankings': [],
            'scores': [],
            'competition_data': [],
            'product_counts': [],
            'percentages': [],
            'other_financial': []
        }
        
        text_content = ""
        tables_data = []
        
        # First try regular text extraction
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Extract text
                page_text = page.extract_text()
                if page_text:
                    text_content += page_text + "\n"
                
                # Extract tables (PDFs often have structured data in tables)
                tables = page.extract_tables()
                for table in tables:
                    tables_data.extend([cell for row in table for cell in row if cell])
        
        # If no text found, try OCR approach
        if not text_content.strip():
            try:
                import pytesseract
                from pdf2image import convert_from_path
                
                # Convert PDF pages to images
                images = convert_from_path(pdf_path)
                
                for image in images:
                    # Extract text from image using OCR
                    page_text = pytesseract.image_to_string(image)
                    if page_text:
                        text_content += page_text + "\n"
                        
            except ImportError:
                pass  # OCR libraries not available
            except Exception:
                pass  # OCR failed
        
        # Combine text and table data for pattern matching
        all_content = text_content + " " + " ".join(str(item) for item in tables_data if item)
        
        # Use the new structured extraction
        if all_content.strip():
            return extract_smartscout_data(all_content)
        else:
            return {
                'weekly_revenue': None,
                'revenue_change': None,
                'market_categories': [],
                'brand_data': [],
                'product_data': [],
                'asin_data': [],
                'search_terms': [],
                'keyword_metrics': {},
                'competitor_data': {},
                'all_revenue_figures': [],
                'all_percentages': []
            }
        
    except ImportError:
        return {"error": "pdfplumber library not installed. Please install with: pip install pdfplumber"}
    except Exception as e:
        return {"error": f"Error extracting PDF metrics: {str(e)}"}

def extract_metrics_from_html(html_content: str) -> dict:
    """
    Extract specific metrics from SmartScout report HTML.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    metrics = {
        'revenue_data': [],
        'growth_data': [],
        'rankings': [],
        'scores': [],
        'competition_data': [],
        'product_counts': [],
        'percentages': [],
        'other_financial': []
    }
    
    # Get all text content
    text = soup.get_text()
    
    import re
    
    # Revenue patterns
    revenue_patterns = [
        r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|M|thousand|K|billion|B))?',
        r'Revenue:?\s*\$[\d,]+',
        r'Monthly.*?\$[\d,]+',
        r'Sales:?\s*\$[\d,]+'
    ]
    
    # Growth patterns  
    growth_patterns = [
        r'[+\-]?\d+(?:\.\d+)?%\s*(?:growth|increase|decrease|change)',
        r'(?:up|down|grew|declined)\s*\d+(?:\.\d+)?%',
        r'Growth:?\s*[+\-]?\d+(?:\.\d+)?%'
    ]
    
    # Ranking patterns
    ranking_patterns = [
        r'#\d+(?:\s*(?:rank|position|place))?',
        r'Rank(?:ed)?:?\s*#?\d+',
        r'Position:?\s*#?\d+',
        r'Top\s*\d+'
    ]
    
    # Score patterns
    score_patterns = [
        r'Score:?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+)?',
        r'Rating:?\s*\d+(?:\.\d+)?',
        r'\d+(?:\.\d+)?\s*(?:out of|/)\s*\d+'
    ]
    
    # Competition patterns
    competition_patterns = [
        r'\d+(?:,\d{3})*\s*(?:sellers|competitors|brands)',
        r'Competition:?\s*\d+',
        r'Market share:?\s*\d+(?:\.\d+)?%'
    ]
    
    # Product count patterns
    product_patterns = [
        r'\d+(?:,\d{3})*\s*(?:products|items|SKUs|listings)',
        r'Products:?\s*\d+(?:,\d{3})*'
    ]
    
    # General percentage patterns
    percentage_patterns = [
        r'\d+(?:\.\d+)?%(?!\s*(?:growth|increase|decrease))'
    ]
    
    # Extract metrics using patterns
    pattern_groups = [
        (revenue_patterns, 'revenue_data'),
        (growth_patterns, 'growth_data'), 
        (ranking_patterns, 'rankings'),
        (score_patterns, 'scores'),
        (competition_patterns, 'competition_data'),
        (product_patterns, 'product_counts'),
        (percentage_patterns, 'percentages')
    ]
    
    for patterns, key in pattern_groups:
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            metrics[key].extend(matches[:10])  # Limit matches per pattern
    
    # Look for other financial data
    other_financial_patterns = [
        r'\$[\d,]+(?:\.\d{2})?(?!\s*(?:million|thousand|billion))',
        r'Cost:?\s*\$[\d,]+',
        r'Price:?\s*\$[\d,]+'
    ]
    
    for pattern in other_financial_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metrics['other_financial'].extend(matches[:5])
    
    # Remove duplicates and clean up
    for key in metrics:
        metrics[key] = list(set(metrics[key]))[:10]  # Remove dupes, limit to 10
    
    return metrics

def filter_html_for_llm_processing(html_content: str) -> str:
    """
    Filter HTML content to extract only relevant SmartScout data sections,
    significantly reducing token count by removing CSS, JavaScript, and non-essential elements.
    
    Based on analysis of SmartScout report structure, this function extracts:
    - Revenue and growth data
    - Brand scores and metrics
    - Market share data
    - Top products and competitor products
    - Search terms and keyword rankings
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove all non-essential elements that add tokens but no value
    for element in soup(["script", "style", "link", "meta", "noscript", "iframe", "svg"]):
        element.decompose()
    
    # Remove comments
    from bs4 import Comment
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # Keep only specific data-rich sections
    relevant_sections = []
    
    # 1. Extract revenue and overview data
    overview_sections = soup.find_all(class_=lambda x: x and any(term in str(x).lower() for term in [
        'overview-report', 'revenue', 'growth', 'brand-score', 'brand-info'
    ]))
    relevant_sections.extend(overview_sections)
    
    # 2. Extract market share data
    market_sections = soup.find_all(class_=lambda x: x and any(term in str(x).lower() for term in [
        'market-share', 'market-grid', 'competitor'
    ]))
    relevant_sections.extend(market_sections)
    
    # 3. Extract top products data
    product_sections = soup.find_all(class_=lambda x: x and any(term in str(x).lower() for term in [
        'top-product', 'product-info', 'product-revenue', 'search-terms'
    ]))
    relevant_sections.extend(product_sections)
    
    # 4. Extract any elements containing monetary values or percentages
    monetary_elements = soup.find_all(string=lambda text: text and (
        '$' in str(text) or '%' in str(text) or 
        'revenue' in str(text).lower() or 'rank' in str(text).lower()
    ))
    for element in monetary_elements:
        if element.parent:
            relevant_sections.append(element.parent)
    
    # 5. Extract elements with specific data attributes or text content
    data_rich_elements = soup.find_all(lambda tag: tag and (
        # Elements with numbers that could be search volumes or rankings
        any(char.isdigit() and ('search' in tag.get_text().lower() or 
                               'rank' in tag.get_text().lower() or
                               'term' in tag.get_text().lower()) for char in tag.get_text()[:100]) or
        # Elements containing brand names or product titles
        any(term in tag.get_text().lower() for term in ['brand', 'product', 'title', 'keyword'])
    ))
    relevant_sections.extend(data_rich_elements[:50])  # Limit to prevent over-extraction
    
    # Create a new soup with only relevant sections
    filtered_soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    body = filtered_soup.body
    
    # Add unique relevant sections (avoid duplicates)
    added_elements = set()
    for section in relevant_sections:
        if section and hasattr(section, 'get_text'):
            section_text = section.get_text()[:100]  # First 100 chars as identifier
            if section_text not in added_elements and len(section_text.strip()) > 10:
                # Clone the element to avoid issues with moving between documents
                try:
                    new_section = soup.new_tag("div")
                    new_section.string = section.get_text()
                    new_section['class'] = section.get('class', ['extracted-data'])
                    body.append(new_section)
                    added_elements.add(section_text)
                except Exception as e:
                    # Fallback to text extraction if element cloning fails
                    text_div = soup.new_tag("div")
                    text_div.string = section.get_text()
                    body.append(text_div)
    
    filtered_html = str(filtered_soup)
    
    # Calculate compression ratio
    original_size = len(html_content)
    filtered_size = len(filtered_html)
    compression_ratio = (1 - filtered_size / original_size) * 100
    
    print(f"📊 HTML Filtering Results:")
    print(f"   Original: {original_size:,} chars")
    print(f"   Filtered: {filtered_size:,} chars")
    print(f"   Reduction: {compression_ratio:.1f}%")
    
    return filtered_html

def extract_text_from_html(html_content: str) -> str:
    """
    Extract readable text from HTML content, focusing on report data.
    First applies HTML filtering to reduce token count, then extracts text.
    """
    # Apply HTML filtering first to reduce content
    filtered_html = filter_html_for_llm_processing(html_content)
    
    soup = BeautifulSoup(filtered_html, 'html.parser')
    
    # Remove any remaining script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get text content
    text = soup.get_text()
    
    # Clean up text - remove extra whitespace and normalize
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return text

def process_with_smart_chunking(client, html_content: str, brand_name: str) -> str:
    """
    Process large HTML content with intelligent chunking that preserves structure.
    First applies HTML filtering to significantly reduce token count.
    """
    try:
        # Apply HTML filtering first to reduce content size
        print("🔧 Applying HTML filtering to reduce token count...")
        filtered_html = filter_html_for_llm_processing(html_content)
        
        # Use filtered HTML for processing
        working_content = filtered_html
        
        # Extract key sections that should stay together
        chunk_size = 120000  # Conservative size to stay under token limits
        chunks = []
        
        # Try to split on logical HTML boundaries
        section_markers = [
            '<table', '</table>',
            '<div class="brand-report', '</div>',
            '<section', '</section>',
            'class="keyword', 'class="product',
            'class="competitor', 'class="search-term'
        ]
        
        current_chunk = ""
        lines = working_content.split('\n')
        
        for line in lines:
            # If adding this line would exceed chunk size and we have content
            if len(current_chunk + line) > chunk_size and current_chunk.strip():
                # Check if we're at a good breaking point
                is_good_break = any(marker in line.lower() for marker in ['</table>', '</div>', '</section>'])
                
                if is_good_break or len(current_chunk) > chunk_size * 0.8:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + '\n'
                else:
                    current_chunk += line + '\n'
            else:
                current_chunk += line + '\n'
        
        # Add remaining content
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        print(f"📄 Split into {len(chunks)} intelligent chunks")
        
        # Process each chunk
        chunk_results = []
        for i, chunk in enumerate(chunks):
            print(f"🔍 Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
            
            chunk_prompt = f"""Analyze this SmartScout data chunk for "{brand_name}" and extract ALL product/keyword data:

**EXTRACT FROM THIS CHUNK:**
1. **Product names/titles** with their keywords and search volumes
2. **Competitor products** with their keywords and search volumes  
3. **Market share of top subcategories** (percentages and category names)
4. **Top competitor brands** (names, market shares, changes)
5. **Top product and competitor searches** (search terms with volumes)
6. **Top keyword distribution** (keyword rankings 1-3, 4-10, 11-50, etc.)
7. **TOP PRODUCT VS. TOP COMPETING PRODUCT comparisons:**
   - Product names (brand product vs competitor product)
   - Sales ranks for each
   - Monthly revenue for each  
   - Search terms and their ranks for each product
   - Any head-to-head comparison data
8. **All keywords** with search volume numbers
9. **All numerical data** (rankings, search volumes, revenue, percentages, etc.)
10. **Table data** if present (preserve complete table structures)

Format findings clearly. Extract ALL data - don't summarize or skip details.

Chunk {i+1}/{len(chunks)}:
{chunk}"""
            
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-0",
                    max_tokens=4000,
                    temperature=0.3,
                    messages=[{"role": "user", "content": chunk_prompt}]
                )
                chunk_results.append(response.content[0].text)
                print(f"✅ Processed chunk {i+1}/{len(chunks)}")
                
            except Exception as e:
                print(f"⚠ Error processing chunk {i+1}: {e}")
                chunk_results.append(f"Error processing chunk {i+1}: {e}")
        
        # Final synthesis
        print("🔄 Synthesizing all chunk results...")
        
        synthesis_prompt = f"""Combine all chunk analyses into a comprehensive PRODUCT COMPARISON REPORT for "{brand_name}":

## COMPREHENSIVE PRODUCT COMPARISON ANALYSIS: {brand_name}
**Report Metadata:** File size: unknown KB | Content: {len(html_content):,} characters

### Brand Overview:
- Weekly Revenue
- Revenue Change (dollar and percentage)

### MARKET SHARE OF TOP SUBCATEGORIES:
**Category Breakdown:**
- List ALL subcategories with market share percentages
- Include category names and share changes

### TOP COMPETITOR BRANDS:
**Market Share Leaders:**
- List ALL competitor brands with market shares and changes
- Include brand names, percentages, and growth/decline data

### TOP PRODUCT VS. TOP COMPETING PRODUCT:
**Head-to-Head Product Comparison:**
- **{brand_name} Top Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Top Competitor Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Direct Comparison Data:** [any side-by-side metrics found]

### TOP PRODUCT AND COMPETITOR SEARCHES:
**Search Term Analysis:**
- List ALL search terms with volumes for main brand products
- List ALL search terms with volumes for competitor products

### SHARED VS UNIQUE KEYWORDS:
- Shared keywords between brands with search volumes
- Unique keywords per brand with search volumes

**CRITICAL INSTRUCTIONS:**
1. ONLY generate the sections listed above - nothing else
2. Do NOT create these sections: "MAIN BRAND PRODUCTS & KEYWORDS", "TOP KEYWORD DISTRIBUTION", "ADDITIONAL DATA", "KEYWORD SEARCH VOLUME COMPARISON"
3. Do NOT include "Summary of Key Findings", "Key Insights", "Conclusions", or any summary sections
4. Do NOT add any sections not specifically requested above
5. Extract data only for the requested sections - no strategic advice needed

STOP after completing the requested sections. Do not generate additional content.

Combine ALL data from chunks below - don't lose any details:

{chr(10).join(chunk_results)}"""
        
        try:
            final_response = client.messages.create(
                model="claude-sonnet-4-0",
                max_tokens=8000,
                temperature=0.3,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
            print("✅ Smart chunking analysis completed")
            return final_response.content[0].text
            
        except Exception as e:
            print(f"⚠ Error in final synthesis: {e}")
            return f"## Chunk Analysis Results\n\n{chr(10).join(chunk_results)}\n\n**Note**: Error in synthesis: {e}"
            
    except Exception as e:
        return f"❌ Error in smart chunking: {str(e)}"

def get_llm_client(model_provider: str):
    """
    Get the appropriate LLM client based on provider.
    """
    if model_provider == "anthropic":
        try:
            import anthropic
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                return None, "❌ Anthropic API key not found. Please set ANTHROPIC_API_KEY environment variable."
            return anthropic.Anthropic(api_key=api_key), None
        except ImportError:
            return None, "❌ Anthropic library not installed. Install with: pip install anthropic"
    
    elif model_provider == "openai":
        try:
            import openai
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                return None, "❌ OpenAI API key not found. Please set OPENAI_API_KEY environment variable."
            return openai.OpenAI(api_key=api_key), None
        except ImportError:
            return None, "❌ OpenAI library not installed. Install with: pip install openai"
    
    elif model_provider == "deepseek":
        try:
            import openai  # DeepSeek uses OpenAI-compatible API
            api_key = os.getenv('DEEPSEEK_API_KEY')
            if not api_key:
                return None, "❌ DeepSeek API key not found. Please set DEEPSEEK_API_KEY environment variable."
            return openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com"), None
        except ImportError:
            return None, "❌ OpenAI library required for DeepSeek. Install with: pip install openai"
    
    elif model_provider == "gemini":
        try:
            import google.generativeai as genai
            api_key = os.getenv('GEMINI_API_KEY')
            if not api_key:
                return None, "❌ Gemini API key not found. Please set GEMINI_API_KEY environment variable."
            genai.configure(api_key=api_key)
            return genai, None
        except ImportError:
            return None, "❌ Google Generative AI library not installed. Install with: pip install google-generativeai"
    
    else:
        return None, f"❌ Unsupported model provider: {model_provider}. Supported: anthropic, openai, deepseek, gemini"

def call_llm_api(client, model_provider: str, prompt: str, model_name: str = None):
    """
    Make API call to the specified LLM provider.
    """
    try:
        if model_provider == "anthropic":
            model = model_name or "claude-3-5-sonnet-20241022"
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        
        elif model_provider in ["openai", "deepseek"]:
            if model_provider == "openai":
                model = model_name or "gpt-5-mini"
            else:  # deepseek
                model = model_name or "deepseek-chat"
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.3
            )
            return response.choices[0].message.content
        
        elif model_provider == "gemini":
            model_name = model_name or "gemini-2.5-flash-lite"
            model = client.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        
    except Exception as e:
        return f"❌ Error calling {model_provider} API: {str(e)}"

def summarize_with_llm(text_content: str, brand_name: str, metrics: dict, model_provider: str = "gemini", model_name: str = None) -> str:
    """
    Summarize the report content using specified LLM provider.
    """
    try:
        # Get LLM client
        client, error = get_llm_client(model_provider)
        if error:
            return error
        
        # Get HTML content if available, otherwise use text_content
        if metrics.get('html_content'):
            content_to_analyze = metrics['html_content']
            content_type = "HTML"
        else:
            content_to_analyze = text_content
            content_type = "text"
        
        print(f"📊 Processing {len(content_to_analyze)} characters of {content_type} content with {model_provider}")
        
        # Check if content is too large for single request (adjust limits per provider)
        token_limits = {
            "anthropic": 150000,
            "openai": 120000,      # GPT-4 has smaller context
            "deepseek": 180000,    # DeepSeek has larger context
            "gemini": 200000       # Gemini Pro has large context
        }
        
        limit = token_limits.get(model_provider, 150000)
        
        if len(content_to_analyze) > limit:
            print(f"📄 Content too large for {model_provider}, using intelligent chunking...")
            return process_with_smart_chunking_multi_llm(client, content_to_analyze, brand_name, model_provider, model_name, metrics)
        
        # Get file size info for the prompt
        file_size_kb = metrics.get('file_size_kb', 'unknown')
        content_length = metrics.get('content_length', len(content_to_analyze))
        
        # Single request for smaller content
        prompt = f"""Please analyze this complete SmartScout brand report for "{brand_name}" and create a COMPREHENSIVE PRODUCT COMPARISON ANALYSIS:

## COMPREHENSIVE PRODUCT COMPARISON ANALYSIS: {brand_name}
**Report Metadata:** File size: {file_size_kb} KB | Content: {content_length:,} characters

### Brand Overview:
- Weekly Revenue
- Revenue Change (dollar and percentage)
** do not generate MAIN BRAND PRODUCTS & KEYWORDS **

### MARKET SHARE OF TOP SUBCATEGORIES:
**Category Breakdown:**
- List ALL subcategories with market share percentages
- Include category names and share changes

### TOP COMPETITOR BRANDS:
**Market Share Leaders:**
- List ALL competitor brands with market shares and changes
- Include brand names, percentages, and growth/decline data

### TOP PRODUCT VS. TOP COMPETING PRODUCT:
**Head-to-Head Product Comparison:**
- **{brand_name} Top Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Top Competitor Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Direct Comparison Data:** [any side-by-side metrics found]

### TOP PRODUCT AND COMPETITOR SEARCHES:
**Search Term Analysis:**
- List ALL search terms with volumes for main brand products
- List ALL search terms with volumes for competitor products

### SHARED VS UNIQUE KEYWORDS:
- Shared keywords between brands with search volumes
- Unique keywords per brand with search volumes

**CRITICAL INSTRUCTIONS:**
1. ONLY generate the sections listed above - nothing else
2. Do NOT create these sections: "MAIN BRAND PRODUCTS & KEYWORDS", "TOP KEYWORD DISTRIBUTION", "ADDITIONAL DATA", "KEYWORD SEARCH VOLUME COMPARISON"
3. Do NOT include "Summary of Key Findings", "Key Insights", "Conclusions", or any summary sections
4. Do NOT add any sections not specifically requested above
5. Extract data only for the requested sections - no strategic advice needed

STOP after completing the requested sections. Do not generate additional content.

Complete HTML content:
{content_to_analyze}"""
        
        # Make API call
        result = call_llm_api(client, model_provider, prompt, model_name)
        if result.startswith("❌"):
            return result
            
        print("✅ Analysis completed in single request")
        return result
        
    except Exception as e:
        return f"❌ Error generating summary: {str(e)}"

def process_with_smart_chunking_multi_llm(client, html_content: str, brand_name: str, model_provider: str, model_name: str = None, metrics: dict = None) -> str:
    """
    Process large HTML content with intelligent chunking for multiple LLM providers.
    First applies HTML filtering to significantly reduce token count.
    """
    try:
        # Apply HTML filtering first to reduce content size
        print("🔧 Applying HTML filtering to reduce token count...")
        filtered_html = filter_html_for_llm_processing(html_content)
        
        # Use filtered HTML for processing
        working_content = filtered_html
        
        # Adjust chunk sizes based on provider
        chunk_sizes = {
            "anthropic": 120000,
            "openai": 100000,      
            "deepseek": 140000,    
            "gemini": 160000       
        }
        
        chunk_size = chunk_sizes.get(model_provider, 120000)
        chunks = []
        
        # Split content into chunks
        current_chunk = ""
        lines = working_content.split('\n')
        
        for line in lines:
            if len(current_chunk + line) > chunk_size and current_chunk.strip():
                is_good_break = any(marker in line.lower() for marker in ['</table>', '</div>', '</section>'])
                
                if is_good_break or len(current_chunk) > chunk_size * 0.8:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + '\n'
                else:
                    current_chunk += line + '\n'
            else:
                current_chunk += line + '\n'
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        print(f"📄 Split into {len(chunks)} intelligent chunks for {model_provider}")
        
        # Process each chunk
        chunk_results = []
        for i, chunk in enumerate(chunks):
            print(f"🔍 Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
            
            chunk_prompt = f"""Analyze this SmartScout data chunk for "{brand_name}" and extract ALL product/keyword data:

**EXTRACT FROM THIS CHUNK:**
1. **Product names/titles** with their keywords and search volumes
2. **Competitor products** with their keywords and search volumes  
3. **Market share of top subcategories** (percentages and category names)
4. **Top competitor brands** (names, market shares, changes)
5. **Top product and competitor searches** (search terms with volumes)
6. **Top keyword distribution** (keyword rankings 1-3, 4-10, 11-50, etc.)
7. **TOP PRODUCT VS. TOP COMPETING PRODUCT comparisons:**
   - Product names (brand product vs competitor product)
   - Sales ranks for each
   - Monthly revenue for each  
   - Search terms and their ranks for each product
   - Any head-to-head comparison data
8. **All keywords** with search volume numbers
9. **All numerical data** (rankings, search volumes, revenue, percentages, etc.)
10. **Table data** if present (preserve complete table structures)

Format findings clearly. Extract ALL data - don't summarize or skip details.

Chunk {i+1}/{len(chunks)}:
{chunk}"""
            
            result = call_llm_api(client, model_provider, chunk_prompt, model_name)
            if not result.startswith("❌"):
                chunk_results.append(result)
                print(f"✅ Processed chunk {i+1}/{len(chunks)}")
            else:
                print(f"⚠ Error processing chunk {i+1}: {result}")
                chunk_results.append(f"Error processing chunk {i+1}: {result}")
        
        # Final synthesis
        print("🔄 Synthesizing all chunk results...")
        # Get file size info for the prompt
        file_size_kb = metrics.get('file_size_kb', 'unknown') if metrics else 'unknown'
        content_length = metrics.get('content_length', len(html_content)) if metrics else len(html_content)
        
        synthesis_prompt = f"""Combine all chunk analyses into a comprehensive PRODUCT COMPARISON REPORT for "{brand_name}":

## COMPREHENSIVE PRODUCT COMPARISON ANALYSIS: {brand_name}
**Report Metadata:** File size: {file_size_kb} KB | Content: {content_length:,} characters

### Brand Overview:
- Weekly Revenue
- Revenue Change (dollar and percentage)

### MARKET SHARE OF TOP SUBCATEGORIES:
**Category Breakdown:**
- List ALL subcategories with market share percentages
- Include category names and share changes

### TOP COMPETITOR BRANDS:
**Market Share Leaders:**
- List ALL competitor brands with market shares and changes
- Include brand names, percentages, and growth/decline data

### TOP PRODUCT VS. TOP COMPETING PRODUCT:
**Head-to-Head Product Comparison:**
- **{brand_name} Top Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Top Competitor Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Direct Comparison Data:** [any side-by-side metrics found]

### TOP PRODUCT AND COMPETITOR SEARCHES:
**Search Term Analysis:**
- List ALL search terms with volumes for main brand products
- List ALL search terms with volumes for competitor products

### SHARED VS UNIQUE KEYWORDS:
- Shared keywords between brands with search volumes
- Unique keywords per brand with search volumes

**CRITICAL INSTRUCTIONS:**
1. ONLY generate the sections listed above - nothing else
2. Do NOT create these sections: "MAIN BRAND PRODUCTS & KEYWORDS", "TOP KEYWORD DISTRIBUTION", "ADDITIONAL DATA", "KEYWORD SEARCH VOLUME COMPARISON"
3. Do NOT include "Summary of Key Findings", "Key Insights", "Conclusions", or any summary sections
4. Do NOT add any sections not specifically requested above
5. Extract data only for the requested sections - no strategic advice needed

STOP after completing the requested sections. Do not generate additional content.

Combine ALL data from chunks below - don't lose any details:

{chr(10).join(chunk_results)}"""
        
        result = call_llm_api(client, model_provider, synthesis_prompt, model_name)
        if not result.startswith("❌"):
            print("✅ Smart chunking analysis completed")
            return result
        else:
            print(f"⚠ Error in final synthesis: {result}")
            return f"## Chunk Analysis Results\n\n{chr(10).join(chunk_results)}\n\n**Note**: Error in synthesis: {result}"
            
    except Exception as e:
        return f"❌ Error in smart chunking: {str(e)}"

def process_csv_with_column(csv_file: str, column_name: str, action_type: str, force_regenerate: bool = False, headless: bool = False):
    """
    Process brands from a specific column in a CSV file.
    Defaults to 'Brand Name' column if no column specified.
    """
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas library required for CSV column reading. Install with: pip install pandas")
        return
    
    try:
        # Read CSV file
        df = pd.read_csv(csv_file)
        print(f"📄 Loaded CSV file: {csv_file}")
        print(f"📊 Available columns: {list(df.columns)}")
        
        # Auto-detect Brand Name column if not specified
        if not column_name:
            # Try common brand column names
            brand_columns = ["Brand Name", "brand name", "Brand", "brand", "Brand_Name", "BRAND NAME"]
            for col in brand_columns:
                if col in df.columns:
                    column_name = col
                    print(f"✅ Auto-detected brand column: '{column_name}'")
                    break
            
            if not column_name:
                print(f"❌ No 'Brand Name' column found automatically")
                print(f"💡 Available columns: {list(df.columns)}")
                print(f"💡 Use --column parameter to specify column name")
                return
        
        # Check if specified column exists
        if column_name not in df.columns:
            print(f"❌ Column '{column_name}' not found in CSV file")
            print(f"💡 Available columns: {list(df.columns)}")
            return
        
        # Extract brand names from the specified column
        brands = df[column_name].dropna().astype(str).str.strip().tolist()
        brands = [brand for brand in brands if brand and brand.lower() != 'nan']
        
        print(f"✅ Found {len(brands)} brands in column '{column_name}'")
        
        if not brands:
            print("❌ No valid brand names found in the specified column")
            return
        
        # Show preview of brands
        print(f"\n🔍 Brand names to process:")
        for i, brand in enumerate(brands[:10], 1):  # Show first 10
            print(f"  {i}. {brand}")
        if len(brands) > 10:
            print(f"  ... and {len(brands) - 10} more")
        print()
        
        # Process brands with CSV output functionality
        process_brands_with_csv_output(df, brands, column_name, csv_file, action_type, headless, force_regenerate)
        
    except FileNotFoundError:
        print(f"❌ CSV file not found: {csv_file}")
    except Exception as e:
        print(f"❌ Error processing CSV file: {e}")

def process_brands_with_csv_output(df, brands: list, brand_column: str, csv_file: str, action_type: str, headless=False, force_regenerate=False):
    """
    Process brands with CSV output functionality and deduplication.
    """
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas library required for CSV output. Install with: pip install pandas")
        return
    
    if not brands:
        print("❌ No brands found to process")
        return
    
    print(f"🚀 Starting batch {action_type} for {len(brands)} brands with CSV output")
    
    # Add Brand Data column if it doesn't exist
    if "Brand Data" not in df.columns:
        df["Brand Data"] = ""
    
    # Track processed brands to avoid duplicates
    processed_brands = {}
    brand_results = {"collected": [], "no_button": [], "not_found_in_search": [], "error": []} if action_type == "collect" else None
    
    # Track summary processing status for reporting
    summary_status = {
        "existing_summary_found": [],
        "new_summary_generated": [], 
        "html_file_missing": [],
        "errors": []
    } if action_type == "summary" else None
    
    # Get unique brands while preserving order
    unique_brands = []
    seen_brands = set()
    for brand in brands:
        brand_clean = brand.strip()
        if brand_clean and brand_clean.lower() not in seen_brands:
            unique_brands.append(brand_clean)
            seen_brands.add(brand_clean.lower())
    
    print(f"📊 Processing {len(unique_brands)} unique brands (found {len(brands) - len(unique_brands)} duplicates)")
    
    # Process each unique brand
    for i, brand in enumerate(unique_brands, 1):
        print(f"{'='*60}")
        print(f"Processing {i}/{len(unique_brands)}: {brand}")
        print(f"{'='*60}")
        
        try:
            brand_data = ""
            result = None
            
            if action_type == "collect":
                result = collect_brand_data(brand, return_result=True, headless=headless)
                if result:
                    brand_results[result].append(brand)
                brand_data = f"Collect Status: {result}" if result else "Collect Status: unknown"
                
            elif action_type == "download":
                download_html_only(brand, headless=headless)
                brand_data = "Download Status: completed"
                
            elif action_type == "summary":
                model_provider = getattr(sys.modules[__name__], '_current_model_provider', 'gemini')
                model_name = getattr(sys.modules[__name__], '_current_model_name', None)
                summary = summarize_html(brand, model_provider, model_name, force_regenerate)
                
                # Track the status of this summary operation
                status = globals().get('_summary_status', 'unknown')
                if status == 'existing':
                    summary_status["existing_summary_found"].append(brand)
                elif status == 'generated':
                    summary_status["new_summary_generated"].append(brand)
                elif status == 'html_missing':
                    summary_status["html_file_missing"].append(brand)
                elif status == 'error':
                    summary_status["errors"].append(brand)
                
                if summary and not summary.startswith("❌"):
                    brand_data = summary
                else:
                    brand_data = "Summary Status: error or not available"
            
            # Store result for this brand
            processed_brands[brand.lower()] = brand_data
            
            # Small delay between brands - skip delay for summary operations that used existing files
            if action_type == "summary":
                used_existing = globals().get('_used_existing_summary', False)
                if i < len(unique_brands) and not used_existing:
                    print(f"\n⏳ Waiting 3 seconds before processing next brand...\n")
                    time.sleep(3)
                elif i < len(unique_brands):
                    print()  # Just add a line break for clean output
            else:
                # For non-summary operations, always delay
                if i < len(unique_brands):
                    print(f"\n⏳ Waiting 3 seconds before processing next brand...\n")
                    time.sleep(3)
                
        except Exception as e:
            print(f"❌ Error processing {brand}: {e}")
            processed_brands[brand.lower()] = f"Error: {str(e)}"
            if action_type == "collect":
                brand_results["error"].append(brand)
            continue
    
    # Update all rows in the dataframe
    print(f"\n🔄 Updating CSV with brand data...")
    for index, row in df.iterrows():
        brand_name = str(row[brand_column]).strip()
        if brand_name and brand_name.lower() in processed_brands:
            df.at[index, "Brand Data"] = processed_brands[brand_name.lower()]
    
    # Save updated CSV
    output_file = csv_file.replace('.csv', '_with_brand_data.csv')
    df.to_csv(output_file, index=False)
    
    print(f"{'='*60}")
    print(f"✅ Batch {action_type} completed for {len(unique_brands)} unique brands")
    print(f"📄 Updated CSV saved as: {output_file}")
    
    # Special summary for collect operations
    if action_type == "collect" and brand_results:
        print(f"\n📊 COLLECT DATA SUMMARY:")
        print(f"{'='*60}")
        print(f"✅ Data Collection Triggered: {len(brand_results['collected'])} brands")
        if brand_results['collected']:
            for brand in brand_results['collected'][:10]:  # Show first 10
                print(f"   • {brand}")
            if len(brand_results['collected']) > 10:
                print(f"   ... and {len(brand_results['collected']) - 10} more")
        
        print(f"\nℹ️  No Button Found (Already Exists): {len(brand_results['no_button'])} brands")
        print(f"🔍 Not Found in Search: {len(brand_results['not_found_in_search'])} brands")  
        print(f"❌ Errors: {len(brand_results['error'])} brands")
        print(f"\n📈 Success Rate: {len(brand_results['collected'])}/{len(unique_brands)} ({len(brand_results['collected'])/len(unique_brands)*100:.1f}%)")
    
    # Summary report for summary operations
    if action_type == "summary" and summary_status:
        print(f"\n📊 SUMMARY PROCESSING REPORT:")
        print(f"{'='*60}")
        
        # Existing summaries found
        if summary_status["existing_summary_found"]:
            print(f"♻️  Existing Summary Files Used: {len(summary_status['existing_summary_found'])} brands")
            for brand in summary_status["existing_summary_found"][:10]:  # Show first 10
                print(f"   • {brand}")
            if len(summary_status["existing_summary_found"]) > 10:
                print(f"   ... and {len(summary_status['existing_summary_found']) - 10} more")
        
        # New summaries generated
        if summary_status["new_summary_generated"]:
            print(f"\n🧠 New Summaries Generated: {len(summary_status['new_summary_generated'])} brands")
            for brand in summary_status["new_summary_generated"][:10]:  # Show first 10
                print(f"   • {brand}")
            if len(summary_status["new_summary_generated"]) > 10:
                print(f"   ... and {len(summary_status['new_summary_generated']) - 10} more")
        
        # HTML files missing
        if summary_status["html_file_missing"]:
            print(f"\n❌ HTML Files Missing: {len(summary_status['html_file_missing'])} brands")
            for brand in summary_status["html_file_missing"][:10]:  # Show first 10
                print(f"   • {brand}")
            if len(summary_status["html_file_missing"]) > 10:
                print(f"   ... and {len(summary_status['html_file_missing']) - 10} more")
        
        # Errors occurred
        if summary_status["errors"]:
            print(f"\n❌ Processing Errors: {len(summary_status['errors'])} brands")
            for brand in summary_status["errors"][:10]:  # Show first 10
                print(f"   • {brand}")
            if len(summary_status["errors"]) > 10:
                print(f"   ... and {len(summary_status['errors']) - 10} more")
        
        # Success rate calculation
        successful = len(summary_status["existing_summary_found"]) + len(summary_status["new_summary_generated"])
        total = len(unique_brands)
        print(f"\n📈 Summary Success Rate: {successful}/{total} ({successful/total*100:.1f}%)")
        
        # Time and cost savings
        existing_count = len(summary_status["existing_summary_found"])
        new_count = len(summary_status["new_summary_generated"])
        if existing_count > 0:
            print(f"⚡ Time Saved: ~{existing_count * 10} seconds (no API calls for existing summaries)")
            print(f"💰 Estimated Cost Savings: ~{existing_count} API calls avoided")
    
    print(f"{'='*60}")

def process_brand_list(brands_input: str, action_type: str, column_name: str = None, force_regenerate: bool = False, headless: bool = False):
    """
    Process multiple brands from a comma-separated list or file.
    Enhanced version supports CSV column specification with auto-detection.
    """
    # Handle CSV files (with or without column specification)
    if brands_input.endswith('.csv'):
        process_csv_with_column(brands_input, column_name, action_type, force_regenerate, headless)
        return
        
    brands = []
    
    # Check if it's a file path
    if brands_input.endswith('.txt') or brands_input.endswith('.csv'):
        try:
            with open(brands_input, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # Handle both comma-separated and line-separated formats
                if ',' in content:
                    brands = [brand.strip() for brand in content.split(',') if brand.strip()]
                else:
                    brands = [brand.strip() for brand in content.split('\n') if brand.strip()]
            print(f"📄 Loaded {len(brands)} brands from file: {brands_input}")
        except FileNotFoundError:
            print(f"❌ File not found: {brands_input}")
            return
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            return
    else:
        # Treat as comma-separated list
        brands = [brand.strip() for brand in brands_input.split(',') if brand.strip()]
        print(f"📝 Processing {len(brands)} brands from list")
    
    process_brand_list_internal(brands, action_type, force_regenerate, headless)

def process_brand_list_internal(brands: list, action_type: str, force_regenerate: bool = False, headless: bool = False):
    """
    Internal function to process a list of brand names.
    """
    if not brands:
        print("❌ No brands found to process")
        return
    
    print(f"🚀 Starting batch {action_type} for brands:")
    for i, brand in enumerate(brands, 1):
        print(f"  {i}. {brand}")
    print()
    
    # Process each brand and track results for collect/download operations
    collect_results = {
        "collected": [], 
        "analyzing": [], 
        "already_available": [], 
        "no_button_unknown": [], 
        "not_found_in_search": [], 
        "error": []
    } if action_type == "collect" else None
    
    download_results = {
        "downloaded": [],
        "not_found_in_search": [],
        "error": []
    } if action_type == "download" else None
    
    for i, brand in enumerate(brands, 1):
        print(f"{'='*60}")
        print(f"Processing {i}/{len(brands)}: {brand}")
        print(f"{'='*60}")
        
        try:
            if action_type == "collect":
                result = collect_brand_data(brand, return_result=True, headless=headless)
                if result:
                    collect_results[result].append(brand)
            elif action_type == "download": 
                result = download_html_only(brand, headless=headless, return_result=True)
                if result:
                    download_results[result].append(brand)
            elif action_type == "summary":
                summarize_html(brand, force_regenerate=force_regenerate)
                
            # Small delay between brands to avoid overwhelming the server
            # Skip delay for summary operations that used existing files
            if action_type == "summary":
                used_existing = globals().get('_used_existing_summary', False)
                if i < len(brands) and not used_existing:
                    print(f"\n⏳ Waiting 3 seconds before processing next brand...\n")
                    time.sleep(3)
                elif i < len(brands):
                    print()  # Just add a line break for clean output
            else:
                # For non-summary operations, always delay
                if i < len(brands):
                    print(f"\n⏳ Waiting 3 seconds before processing next brand...\n")
                    time.sleep(3)
                
        except Exception as e:
            print(f"❌ Error processing {brand}: {e}")
            if action_type == "collect":
                collect_results["error"].append(brand)
            elif action_type == "download":
                download_results["error"].append(brand)
            continue
    
    print(f"{'='*60}")
    print(f"✅ Batch {action_type} completed for {len(brands)} brands")
    
    # Special summary for collect operations
    if action_type == "collect" and collect_results:
        print(f"\n📊 COLLECT DATA SUMMARY:")
        print(f"{'='*60}")
        print(f"✅ Data Collection Triggered: {len(collect_results['collected'])} brands")
        if collect_results['collected']:
            for brand in collect_results['collected']:
                print(f"   • {brand}")
        
        print(f"\n⏳ Currently Analyzing: {len(collect_results['analyzing'])} brands")
        if collect_results['analyzing']:
            for brand in collect_results['analyzing']:
                print(f"   • {brand}")
                
        print(f"\n📋 Already Available: {len(collect_results['already_available'])} brands")
        if collect_results['already_available']:
            for brand in collect_results['already_available']:
                print(f"   • {brand}")
        
        print(f"\nℹ️  No Button Found (Status Unknown): {len(collect_results['no_button_unknown'])} brands") 
        if collect_results['no_button_unknown']:
            for brand in collect_results['no_button_unknown']:
                print(f"   • {brand}")
                
        print(f"\n🔍 Not Found in Search: {len(collect_results['not_found_in_search'])} brands")
        if collect_results['not_found_in_search']:
            for brand in collect_results['not_found_in_search']:
                print(f"   • {brand}")
                
        print(f"\n❌ Errors: {len(collect_results['error'])} brands")
        if collect_results['error']:
            for brand in collect_results['error']:
                print(f"   • {brand}")
                
        successful_collects = len(collect_results['collected'])
        total_brands = len(brands)
        print(f"\n📈 Data Collection Success Rate: {successful_collects}/{total_brands} ({successful_collects/total_brands*100:.1f}%)")
        
        ready_brands = len(collect_results['already_available'])
        if ready_brands > 0:
            print(f"📋 Brands Ready for Download: {ready_brands}")
            
        in_progress = len(collect_results['analyzing'])
        if in_progress > 0:
            print(f"⏳ Brands Currently Processing: {in_progress}")
    
    # Special summary for download operations  
    if action_type == "download" and download_results:
        print(f"\n📊 DOWNLOAD SUMMARY:")
        print(f"{'='*60}")
        print(f"✅ Successfully Downloaded: {len(download_results['downloaded'])} brands")
        if download_results['downloaded']:
            for brand in download_results['downloaded']:
                print(f"   • {brand}")
        
        print(f"\n🔍 Not Found in Search: {len(download_results['not_found_in_search'])} brands")
        if download_results['not_found_in_search']:
            for brand in download_results['not_found_in_search']:
                print(f"   • {brand}")
                
        print(f"\n❌ Errors: {len(download_results['error'])} brands")
        if download_results['error']:
            for brand in download_results['error']:
                print(f"   • {brand}")
                
        successful_downloads = len(download_results['downloaded'])
        total_brands = len(brands)
        print(f"\n📈 Download Success Rate: {successful_downloads}/{total_brands} ({successful_downloads/total_brands*100:.1f}%)")
    
    print(f"{'='*60}")

def collect_brand_data(brand_name: str, return_result=False, headless=False):
    """
    Look for and click 'Collect {Brand Name}'s Data Now' button without downloading report.
    """
    # Create html folder if it doesn't exist (for consistency)
    html_folder = globals().get('_html_folder', 'html')
    if not os.path.exists(html_folder):
        os.makedirs(html_folder)
        print(f"📁 Created {html_folder} folder")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=headless, slow_mo=500 if not headless else 100)
        page = context.new_page()
        print(f"Navigating to the Brand Reports page: {SMARTSCOUT_URL}")
        page.goto(SMARTSCOUT_URL)
        try:
            # 1. Search for the brand in existing reports
            print(f"Searching for brand: '{brand_name}'")
            
            # Wait for page to load
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # Look for search functionality
            search_selectors = [
                'input[placeholder*="search" i]',
                'input[placeholder*="brand" i]',
                'input[type="search"]',
                '.search-input',
                '[data-testid*="search"]'
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    search_input = page.locator(selector).first
                    if search_input.is_visible(timeout=2000):
                        print(f"Found search input with selector: {selector}")
                        break
                except:
                    continue
            
            if search_input and search_input.is_visible():
                print(f"🔍 Searching for brand: {brand_name}")
                search_input.fill(brand_name)
                search_input.press("Enter")
                
                # Wait for search results
                print(f"Waiting for search results...")
                time.sleep(5)  # Simple 5-second wait for results to appear
                
                # Look for the brand name in search results
                print(f"Looking for '{brand_name}' in search results...")
                # EXACT MATCHES ONLY - No partial matching to prevent "Solvite" matching "Solvitek"
                brand_selectors = [
                    f':text-is("{brand_name}")',  # Exact text match only
                    f'[title="{brand_name}"]',  # Exact title match only
                ]
                
                brand_link = None
                # Try multiple times with scrolling to find brands further down
                found = False
                for attempt in range(5):  # Increased attempts to allow for scrolling
                    print(f"Search attempt {attempt + 1}/5...")
                    
                    # Try to find the brand without scrolling first
                    for selector in brand_selectors:
                        try:
                            brand_link = page.locator(selector).first
                            if brand_link.is_visible(timeout=2000):
                                print(f"✅ Found brand link with selector: {selector}")
                                found = True
                                break
                        except:
                            continue
                    
                    if found:  # Exit if found
                        break
                    
                    # If not found, scroll down to load more results
                    if attempt < 4:  # Don't scroll after last attempt
                        print(f"⏳ Brand not found yet, scrolling down to load more results...")
                        # Scroll to bottom of page to trigger loading more results
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(2)  # Wait for more results to load
                
                if brand_link and brand_link.is_visible():
                    print(f"📊 Clicking on '{brand_name}' to open brand page...")
                    brand_link.click()
                    
                    # Wait for brand page to load
                    print("⏳ Waiting for brand page to load...")
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    time.sleep(3)
                else:
                    print(f"❌ Could not find '{brand_name}' in search results")
                    result = "no_brand_found"
                    if return_result:
                        return result
                    return
            else:
                print("❌ Could not find search input")
                result = "error"
                if return_result:
                    return result
                return
            
            # 3. Now look for the 'Collect Brand Data Now' button on the brand page
            print(f"Looking for 'Collect {brand_name}'s Data Now' button on brand page...")
            
            # Try different button selectors for the collect data button
            collect_button_selectors = [
                f'button.white-button:has-text("Collect {brand_name}\'s Data Now")',
                f'button[class*="white-button"]:has-text("Collect {brand_name}\'s Data")',
                f'button:has-text("Collect {brand_name}\'s Data Now")',
                f'button:has-text("Collect {brand_name}\'s Data")',
                f'button.white-button',
                f'button:has-text("Collect {brand_name}")',
                f'button:has-text("Collect Data Now")',
                f'button:has-text("Collect Data")',
                f'[data-testid*="collect"]',
                f'button:has-text("Generate Report")',
                f'a:has-text("Collect {brand_name}\'s Data Now")',
                f'a:has-text("Collect Data")',
                '.collect-button',
                '[class*="collect"]'
            ]
            
            collect_button = None
            for selector in collect_button_selectors:
                try:
                    collect_button = page.locator(selector).first
                    if collect_button.is_visible(timeout=2000):
                        print(f"✅ Found collect data button with selector: {selector}")
                        break
                except:
                    continue
            
            if collect_button and collect_button.is_visible():
                print(f"🎯 Clicking 'Collect {brand_name}'s Data Now' button...")
                collect_button.click()
                time.sleep(2)
                print(f"✅ Data collection triggered for '{brand_name}'")
                print("💡 Report will be generated in the background. Check back later to download.")
                result = "collected"
            else:
                # Check if report is being generated (look for progress indicators)
                progress_selectors = [
                    ':text("Analysing")',
                    ':text("Analyzing")', 
                    ':text("Processing")',
                    ':text("Generating")',
                    '[class*="progress"]',
                    '[class*="loading"]',
                    '.spinner',
                    '[data-testid*="progress"]'
                ]
                
                is_analyzing = False
                for selector in progress_selectors:
                    try:
                        if page.locator(selector).first.is_visible(timeout=1000):
                            print(f"📊 Found progress indicator: {selector}")
                            is_analyzing = True
                            break
                    except:
                        continue
                
                # Simplified logic: if no collect button and not analyzing, then it's available
                
                if is_analyzing:
                    print(f"⏳ Report for '{brand_name}' is currently being generated")
                    print("💡 Progress detected - report generation in progress")
                    result = "analyzing"
                else:
                    # If no collect button and not analyzing, then report is ready
                    print(f"✅ Report for '{brand_name}' appears to be ready for download")
                    print("💡 No collect button found and no analysis in progress - report should be available")
                    result = "analyzed"
            
        except Exception as e:
            print(f"❌ An error occurred: {str(e)}")
            result = "error"
        finally:
            context.close()
        
        if return_result:
            return result

def download_html_only(brand_name: str, headless=False, return_result=False, html_folder=None, force_regenerate=False):
    """
    Download HTML report and save to html folder without summarizing.
    If force_regenerate=False, will check existing file size first and skip if complete.
    """
    # Use provided folder path or fall back to global/default
    if html_folder is None:
        html_folder = globals().get('_html_folder', 'html')
    if not os.path.exists(html_folder):
        os.makedirs(html_folder)
        print(f"📁 Created {html_folder} folder")
    
    # Check if file already exists and is complete (unless force_regenerate=True)
    html_filename = f"{brand_name.replace(' ', '_').lower()}_report.html"
    html_file_path = os.path.join(html_folder, html_filename)
    
    if not force_regenerate and os.path.exists(html_file_path):
        existing_size = os.path.getsize(html_file_path)
        existing_size_kb = existing_size // 1024
        
        if existing_size >= 300_000:  # Complete file (300KB+)
            print(f"✅ Found existing complete HTML file: {html_file_path} ({existing_size_kb}KB)")
            if return_result:
                return "downloaded"
            return
        else:
            print(f"⚠️  Found existing partial HTML file: {html_file_path} ({existing_size_kb}KB) - will re-download")
    elif not force_regenerate:
        print(f"📄 No existing HTML file found - will download fresh")
    else:
        print(f"🔄 Force regenerate enabled - will re-download even if file exists")
    
    def _download_and_validate(page, brand_name, html_folder, extended_wait=False):
        """Download and validate HTML file size"""
        wait_time = 15 if extended_wait else 10
        
        print(f"⏳ Waiting for report to load ({wait_time}s)...")
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        time.sleep(wait_time)
        
        print("💾 Saving HTML content...")
        html_content = page.content()
        html_file = os.path.join(html_folder, f"{brand_name.replace(' ', '_').lower()}_report.html")
        
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Check file size
        file_size = os.path.getsize(html_file)
        file_size_kb = file_size // 1024
        
        if file_size < 300_000:  # Less than 300KB
            print(f"⚠️  File size {file_size_kb}KB may be incomplete (expected 300KB+)")
            return "incomplete"
        else:
            print(f"📄 HTML saved as: {html_file} ({file_size_kb}KB)")
            print(f"✅ Download completed! File size looks good.")
            return "downloaded"
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=headless, slow_mo=500 if not headless else 100)
        page = context.new_page()
        print(f"Navigating to the Brand Reports page: {SMARTSCOUT_URL}")
        page.goto(SMARTSCOUT_URL)
        try:
            # 1. Search for the brand in existing reports
            print(f"Searching for existing brand report: '{brand_name}'")
            
            # Wait for page to load
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # Look for search functionality or directly find the brand report
            # Try different search input selectors
            search_selectors = [
                'input[placeholder*="search" i]',
                'input[placeholder*="brand" i]',
                'input[type="search"]',
                '.search-input',
                '[data-testid*="search"]'
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    search_input = page.locator(selector).first
                    if search_input.is_visible(timeout=2000):
                        print(f"Found search input with selector: {selector}")
                        break
                except:
                    continue
            
            if search_input and search_input.is_visible():
                print(f"🔍 Searching for brand: {brand_name}")
                search_input.fill(brand_name)
                search_input.press("Enter")
                time.sleep(3)
            
            # 2. Look for the specific brand report link
            print(f"Looking for '{brand_name}' report link...")
            
            # EXACT MATCHES ONLY - No partial matching to prevent "Solvite" matching "Solvitek"
            brand_selectors = [
                f':text-is("{brand_name}")',  # Exact text match only
                f'[title="{brand_name}"]',  # Exact title match only
                f'[data-brand="{brand_name}"]',  # Exact data attribute only
            ]
            
            brand_link = None
            # Try multiple times with scrolling to find brands further down
            found = False
            for attempt in range(5):  # Increased attempts to allow for scrolling
                print(f"Download search attempt {attempt + 1}/5...")
                
                # Try to find the brand without scrolling first
                for selector in brand_selectors:
                    try:
                        brand_link = page.locator(selector).first
                        if brand_link.is_visible(timeout=2000):
                            print(f"✅ Found brand report with selector: {selector}")
                            found = True
                            break
                    except:
                        continue
                
                if found:  # Exit if found
                    break
                
                # If not found, scroll down to load more results
                if attempt < 4:  # Don't scroll after last attempt
                    print(f"⏳ Brand report not found yet, scrolling down to load more results...")
                    # Scroll to bottom of page to trigger loading more results
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)  # Wait for more results to load
            
            if not brand_link or not brand_link.is_visible():
                # EXACT MATCHES ONLY - No partial matching to prevent "Solvite" matching "Solvitek"
                print(f"🔍 Trying exact text search for '{brand_name}'...")
                try:
                    brand_link = page.get_by_text(brand_name, exact=True).first
                    if brand_link.is_visible(timeout=2000):
                        print("✅ Found brand report using exact text search")
                    else:
                        raise Exception("Exact match not found")
                except:
                    print(f"❌ Could not find exact match for brand report '{brand_name}'")
                    print("Available reports on page:")
                    # Try to list available reports for debugging
                    try:
                        reports = page.locator('a, button').all()
                        for report in reports[:10]:
                            try:
                                text = report.inner_text(timeout=1000)
                                if text and len(text.strip()) > 0:
                                    print(f"  - {text.strip()}")
                            except:
                                pass
                    except:
                        pass
                    result = "not_found_in_search"
                    if return_result:
                        return result
                    return
            
            # 3. Click on the brand report
            print(f"📊 Opening '{brand_name}' report...")
            brand_link.click()
            
            # Wait for the report to load and validate completeness
            result = _download_and_validate(page, brand_name, html_folder)
            
            if result == "incomplete":
                print("⚠️  File appears incomplete, retrying with longer wait...")
                result = _download_and_validate(page, brand_name, html_folder, extended_wait=True)
            
        except Exception as e:
            print(f"❌ An error occurred: {str(e)}")
            result = "error"
        finally:
            context.close()
        
        if return_result:
            return result

def summarize_html(brand_name: str, model_provider: str = "gemini", model_name: str = None, force_regenerate: bool = False, html_folder=None, summary_folder=None):
    """
    Generate LLM summary from existing HTML file.
    If force_regenerate is True, will recreate the summary even if it already exists.
    Sets global _summary_status to track what happened: 'existing', 'generated', 'html_missing', or 'error'
    """
    # Use provided folder paths or fall back to global variables (set by command line args)
    if html_folder is None:
        html_folder = globals().get('_html_folder', 'html')
    if summary_folder is None:
        summary_folder = globals().get('_summary_folder', 'summary')
    
    # Create summary folder if it doesn't exist
    if not os.path.exists(summary_folder):
        os.makedirs(summary_folder)
        print(f"📁 Created {summary_folder} folder")
    
    # Find HTML file and summary file paths
    html_file = os.path.join(html_folder, f"{brand_name.replace(' ', '_').lower()}_report.html")
    summary_file = os.path.join(summary_folder, f"{brand_name.replace(' ', '_').lower()}_analysis.txt")
    
    # Check if summary already exists (unless force regenerate is enabled)
    if os.path.exists(summary_file) and not force_regenerate:
        # Check if HTML file is newer than summary file
        try:
            html_mtime = os.path.getmtime(html_file)
            summary_mtime = os.path.getmtime(summary_file)
            
            if html_mtime > summary_mtime:
                print(f"📄 Found existing summary: {summary_file}")
                print(f"🔄 HTML file is newer than summary - will regenerate")
                print(f"   HTML: {datetime.fromtimestamp(html_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Summary: {datetime.fromtimestamp(summary_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"📄 Found existing summary: {summary_file}")
                print("♻️  Using existing summary instead of regenerating...")
                try:
                    with open(summary_file, "r", encoding="utf-8") as f:
                        existing_summary = f.read()
                    print(f"✅ Loaded existing summary ({len(existing_summary)} characters)")
                    # Set global flags to indicate we used existing file
                    globals()['_used_existing_summary'] = True
                    globals()['_summary_status'] = 'existing'
                    return existing_summary
                except Exception as e:
                    print(f"⚠️  Error reading existing summary: {e}")
                    print("🔄 Will generate new summary instead...")
        except OSError as e:
            print(f"⚠️  Error checking file timestamps: {e}")
            print("🔄 Will generate new summary instead...")
    elif os.path.exists(summary_file) and force_regenerate:
        print(f"🔄 Found existing summary but force regenerate enabled: {summary_file}")
    
    # Set global flag to indicate we're generating new summary
    globals()['_used_existing_summary'] = False
    
    if not os.path.exists(html_file):
        error_msg = f"❌ HTML file not found: {html_file}"
        print(error_msg)
        print(f"💡 Run 'python smartscout_downloader.py \"{brand_name}\"' first to download the report")
        globals()['_summary_status'] = 'html_missing'
        return error_msg
    
    try:
        # Read HTML content
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # Get file size information
        file_size = os.path.getsize(html_file)
        file_size_kb = file_size // 1024
        
        print(f"📄 Found HTML file: {html_file}")
        print(f"📊 Processing {len(html_content)} characters of HTML content")
        print(f"📏 File size: {file_size_kb} KB")
        
        # Extract metrics with HTML content and file metadata
        extracted_metrics = {
            'html_content': html_content,
            'file_size_bytes': file_size,
            'file_size_kb': file_size_kb,
            'content_length': len(html_content)
        }
        
        # Generate AI summary
        print(f"\n📝 Generating AI summary of the report with {model_provider}...")
        summary = summarize_with_llm("", brand_name, extracted_metrics, model_provider, model_name)
        
        # Save summary to summary folder
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)
        
        print(f"📄 Summary saved to: {summary_file}")
        
        globals()['_summary_status'] = 'generated'
        return summary
        
    except Exception as e:
        print(f"❌ Error generating summary: {str(e)}")
        globals()['_summary_status'] = 'error'
        return f"❌ Error generating summary: {str(e)}"


def setup_session():
    """
    Opens a browser for the user to log in and save the session.
    """
    print("--- First-Time Setup ---")
    print(f"A browser window will now open. Please log into your SmartScout account.")
    print(f"Navigate to the brand reports section and make sure you can access it.")
    print(f"The session will be saved in the '{USER_DATA_DIR}' directory.")
    print("You can close the browser once you are successfully logged in.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False)
        page = context.new_page()
        page.goto(SMARTSCOUT_URL)

        print("\nWaiting for you to log in and close the browser...")
        page.wait_for_event("close")

    print("\nSetup complete. Your session has been saved.")
    print("You can now run the script with a brand name to generate reports.")

if __name__ == "__main__":
    # Extract column parameter if provided
    column_name = None
    if "--column" in sys.argv:
        try:
            column_index = sys.argv.index("--column")
            if column_index + 1 < len(sys.argv):
                column_name = sys.argv[column_index + 1]
                # Remove --column and column name from argv for normal processing
                sys.argv.pop(column_index + 1)  # Remove column name
                sys.argv.pop(column_index)      # Remove --column
            else:
                print("❌ Column name required after --column")
                sys.exit(1)
        except ValueError:
            pass
    
    # Check for headless mode
    headless = "--headless" in sys.argv
    if headless:
        sys.argv.remove("--headless")
        print("🤖 Running in headless mode (background)")
    else:
        print("🖥️  Running with visible browser windows")
    
    # Show API status
    if SMARTSCOUT_API_KEY:
        print(f"🔑 SmartScout API: Configured (Key: ...{SMARTSCOUT_API_KEY[-8:]})")
    else:
        print("🌐 SmartScout API: Not configured - using browser automation")
        print("💡 For better performance, set up API access with: python smartscout_csv_downloader.py --setup-api")
    
    # Check for force regenerate mode
    force_regenerate = "--force-regenerate" in sys.argv
    if force_regenerate:
        sys.argv.remove("--force-regenerate")
        print("🔄 Force regenerate mode: will recreate existing summaries")
    
    # Check for custom HTML folder path
    html_folder = "html"  # default
    if "--html-folder" in sys.argv:
        try:
            html_index = sys.argv.index("--html-folder")
            if html_index + 1 < len(sys.argv):
                html_folder = sys.argv[html_index + 1]
                # Remove --html-folder and path from argv
                sys.argv.pop(html_index + 1)  # Remove path
                sys.argv.pop(html_index)      # Remove --html-folder
                print(f"📁 Using HTML folder: {html_folder}")
            else:
                print("❌ HTML folder path required after --html-folder")
                sys.exit(1)
        except ValueError:
            pass
    
    # Check for custom summary folder path
    summary_folder = "summary"  # default
    if "--summary-folder" in sys.argv:
        try:
            summary_index = sys.argv.index("--summary-folder")
            if summary_index + 1 < len(sys.argv):
                summary_folder = sys.argv[summary_index + 1]
                # Remove --summary-folder and path from argv
                sys.argv.pop(summary_index + 1)  # Remove path
                sys.argv.pop(summary_index)      # Remove --summary-folder
                print(f"📁 Using summary folder: {summary_folder}")
            else:
                print("❌ Summary folder path required after --summary-folder")
                sys.exit(1)
        except ValueError:
            pass
    
    # Extract model provider and name
    model_provider = "gemini"  # default
    model_name = None
    
    if "--model" in sys.argv:
        try:
            model_index = sys.argv.index("--model")
            if model_index + 1 < len(sys.argv):
                model_spec = sys.argv[model_index + 1]
                if ":" in model_spec:
                    model_provider, model_name = model_spec.split(":", 1)
                else:
                    model_provider = model_spec
                # Remove --model and model spec from argv
                sys.argv.pop(model_index + 1)  # Remove model spec
                sys.argv.pop(model_index)      # Remove --model
                print(f"🤖 Using LLM: {model_provider}" + (f" ({model_name})" if model_name else ""))
            else:
                print("❌ Model specification required after --model")
                sys.exit(1)
        except ValueError:
            pass
    
    # Store model info and folder paths for use in functions
    globals()['_current_model_provider'] = model_provider
    globals()['_current_model_name'] = model_name
    globals()['_html_folder'] = html_folder
    globals()['_summary_folder'] = summary_folder
    
    # Check for help first
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage:")
        print("  For first-time setup (to log in):")
        print("    python smartscout_csv_downloader.py --setup")
        print("\n  🔑 API Authentication Setup (Recommended):")
        print("    python smartscout_csv_downloader.py --setup-api        # Setup SmartScout API key")
        print("\n  To trigger data collection for brand(s):")
        print("    python smartscout_csv_downloader.py --collect \"Brand Name\"")
        print("    python smartscout_csv_downloader.py --collect \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py --collect brands.txt")
        print("    python smartscout_csv_downloader.py --collect brands.csv --column \"Brand Name\"")
        print("\n  To download brand report(s):")
        print("    python smartscout_csv_downloader.py \"Brand Name\"")
        print("    python smartscout_csv_downloader.py \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py brands.txt")
        print("    python smartscout_csv_downloader.py brands.csv --column \"Brand Name\"")
        print("\n  To generate AI summary from existing HTML:")
        print("    python smartscout_csv_downloader.py --summary \"Brand Name\"")
        print("    python smartscout_csv_downloader.py --summary \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py --summary brands.txt")
        print("    python smartscout_csv_downloader.py --summary brands.csv")
        print("    python smartscout_csv_downloader.py --summary results.csv               # Auto-detects 'Brand Name' column")
        print("\n  🤖 Background Processing:")
        print("    python smartscout_csv_downloader.py --collect data.csv --headless        # No browser windows")
        print("    python smartscout_csv_downloader.py data.csv --headless                  # Background download")
        print("    python smartscout_csv_downloader.py --headless \"Brand Name\"             # Single brand headless")
        print("\n  🧠 LLM Model Options:")
        print("    python smartscout_csv_downloader.py --summary data.csv --model deepseek  # Use DeepSeek (cheapest)")
        print("    python smartscout_csv_downloader.py --summary data.csv --model openai    # Use OpenAI GPT-4")
        print("    python smartscout_csv_downloader.py --summary data.csv --model gemini    # Use Google Gemini")
        print("    python smartscout_csv_downloader.py --summary data.csv --model anthropic # Use Claude (default)")
        print("    python smartscout_csv_downloader.py --summary data.csv --model openai:gpt-4o  # Specific model")
        print("\n  🔄 Force Regenerate:")
        print("    python smartscout_csv_downloader.py --summary data.csv --force-regenerate      # Recreate existing summaries")
        print("    python smartscout_csv_downloader.py --summary \"Brand Name\" --force-regenerate # Force single brand")
        print("\n  📁 Custom Folder Paths:")
        print("    python smartscout_csv_downloader.py data.csv --html-folder reports            # Custom HTML folder")
        print("    python smartscout_csv_downloader.py --summary data.csv --summary-folder analysis # Custom summary folder")
        print("    python smartscout_csv_downloader.py data.csv --html-folder /path/to/html --summary-folder /path/to/summaries")
        print("\n  💰 Cost Comparison (approximate):")
        print("    • DeepSeek: ~$0.14 per 1M tokens (cheapest)")
        print("    • OpenAI GPT-4: ~$10-30 per 1M tokens")
        print("    • Gemini Pro: ~$0.50 per 1M tokens")
        print("    • Claude Sonnet: ~$3-15 per 1M tokens")
        sys.exit(0)
    
    if "--setup" in sys.argv:
        setup_session()
    elif "--setup-api" in sys.argv:
        setup_api_key()
    elif "--collect" in sys.argv:
        if len(sys.argv) > 2:
            brands_input = sys.argv[2]
            # Check if it's a list (contains comma) or file (ends with .txt/.csv)
            if ',' in brands_input or brands_input.endswith(('.txt', '.csv')):
                process_brand_list(brands_input, "collect", column_name, force_regenerate, headless)
            else:
                collect_brand_data(brands_input, return_result=False, headless=headless)
        else:
            print("❌ Brand name(s) required for --collect option")
            print("Usage: python smartscout_downloader.py --collect \"Brand Name\"")
            print("   or: python smartscout_downloader.py --collect \"Brand1, Brand2, Brand3\"")
            print("   or: python smartscout_downloader.py --collect brands.txt")
            sys.exit(1)
    elif "--summary" in sys.argv:
        if len(sys.argv) > 2:
            brands_input = sys.argv[2]
            # Check if it's a list (contains comma) or file (ends with .txt/.csv)
            if ',' in brands_input or brands_input.endswith(('.txt', '.csv')):
                process_brand_list(brands_input, "summary", column_name, force_regenerate, headless)
            else:
                summarize_html(brands_input, model_provider, model_name, force_regenerate)
        else:
            print("❌ Brand name(s) required for --summary option")
            print("Usage: python smartscout_csv_downloader.py --summary \"Brand Name\"")
            print("   or: python smartscout_csv_downloader.py --summary \"Brand1, Brand2, Brand3\"")
            print("   or: python smartscout_csv_downloader.py --summary brands.txt")
            print("   or: python smartscout_csv_downloader.py --summary brands.csv --column \"Brand Name\"")
            sys.exit(1)
    elif len(sys.argv) > 1:
        brands_input = sys.argv[1]
        # Check if it's a list (contains comma) or file (ends with .txt/.csv)
        if ',' in brands_input or brands_input.endswith(('.txt', '.csv')):
            process_brand_list(brands_input, "download", column_name, force_regenerate, headless)
        else:
            download_html_only(brands_input, headless=headless)
    else:
        print("Usage:")
        print("  For first-time setup (to log in):")
        print("    python smartscout_csv_downloader.py --setup")
        print("\n  🔑 API Authentication Setup (Recommended):")
        print("    python smartscout_csv_downloader.py --setup-api        # Setup SmartScout API key")
        print("\n  To trigger data collection for brand(s):")
        print("    python smartscout_csv_downloader.py --collect \"Brand Name\"")
        print("    python smartscout_csv_downloader.py --collect \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py --collect brands.txt")
        print("    python smartscout_csv_downloader.py --collect brands.csv --column \"Brand Name\"")
        print("\n  To download brand report(s):")
        print("    python smartscout_csv_downloader.py \"Brand Name\"")
        print("    python smartscout_csv_downloader.py \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py brands.txt")
        print("    python smartscout_csv_downloader.py brands.csv --column \"Brand Name\"")
        print("\n  To generate AI summary from existing HTML:")
        print("    python smartscout_csv_downloader.py --summary \"Brand Name\"")
        print("    python smartscout_csv_downloader.py --summary \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_csv_downloader.py --summary brands.txt")
        print("    python smartscout_csv_downloader.py --summary brands.csv --column \"Brand Name\"")
        print("\n  📊 CSV Examples:")
        print("    python smartscout_csv_downloader.py --collect data.csv                    # Auto-detects 'Brand Name' column")
        print("    python smartscout_csv_downloader.py data.csv --column \"Company Name\"     # Custom column")
        print("    python smartscout_csv_downloader.py --summary results.csv               # Auto-detects 'Brand Name' column")
        print("\n  🤖 Background Processing:")
        print("    python smartscout_csv_downloader.py --collect data.csv --headless        # No browser windows")
        print("    python smartscout_csv_downloader.py data.csv --headless                  # Background download")
        print("    python smartscout_csv_downloader.py --headless \"Brand Name\"             # Single brand headless")
        print("\n  🧠 LLM Model Options:")
        print("    python smartscout_csv_downloader.py --summary data.csv --model deepseek  # Use DeepSeek (cheapest)")
        print("    python smartscout_csv_downloader.py --summary data.csv --model openai    # Use OpenAI GPT-4")
        print("    python smartscout_csv_downloader.py --summary data.csv --model gemini    # Use Google Gemini")
        print("    python smartscout_csv_downloader.py --summary data.csv --model anthropic # Use Claude (default)")
        print("    python smartscout_csv_downloader.py --summary data.csv --model openai:gpt-4o  # Specific model")
        print("\n  🔄 Force Regenerate:")
        print("    python smartscout_csv_downloader.py --summary data.csv --force-regenerate      # Recreate existing summaries")
        print("    python smartscout_csv_downloader.py --summary \"Brand Name\" --force-regenerate # Force single brand")
        print("\n  📁 Custom Folder Paths:")
        print("    python smartscout_csv_downloader.py data.csv --html-folder reports            # Custom HTML folder")
        print("    python smartscout_csv_downloader.py --summary data.csv --summary-folder analysis # Custom summary folder")
        print("    python smartscout_csv_downloader.py data.csv --html-folder /path/to/html --summary-folder /path/to/summaries")
        print("\n  💰 Cost Comparison (approximate):")
        print("    • DeepSeek: ~$0.14 per 1M tokens (cheapest)")
        print("    • OpenAI GPT-4: ~$10-30 per 1M tokens")
        print("    • Gemini Pro: ~$0.50 per 1M tokens")
        print("    • Claude Sonnet: ~$3-15 per 1M tokens")
        sys.exit(1)
