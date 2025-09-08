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
from playwright.sync_api import sync_playwright, expect
from bs4 import BeautifulSoup

# --- Configuration ---
# The directory where your browser session data will be stored.
# This allows you to stay logged in between runs.
USER_DATA_DIR = "./playwright_user_data"
SMARTSCOUT_URL = "https://app.smartscout.com/app/tailored-report"

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

def extract_text_from_html(html_content: str) -> str:
    """
    Extract readable text from HTML content, focusing on report data.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
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
    """
    try:
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
        lines = html_content.split('\n')
        
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

### MAIN BRAND PRODUCTS & KEYWORDS:
**{brand_name}:**
- List ALL products found with ALL their keywords and search volumes

### TOP COMPETITOR BRANDS:
**Market Share Leaders:**
- List ALL competitor brands with market shares and changes
- Include brand names, percentages, and growth/decline data

### MARKET SHARE OF TOP SUBCATEGORIES:
**Category Breakdown:**
- List ALL subcategories with market share percentages
- Include category names and share changes

### TOP PRODUCT VS. TOP COMPETING PRODUCT:
**Head-to-Head Product Comparison:**
- **{brand_name} Top Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Top Competitor Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Direct Comparison Data:** [any side-by-side metrics found]

### TOP PRODUCT AND COMPETITOR SEARCHES:
**Search Term Analysis:**
- List ALL search terms with volumes for main brand products
- List ALL search terms with volumes for competitor products

### TOP KEYWORD DISTRIBUTION:
**Ranking Distribution:**
- Ranked 1-3: [keywords and counts]
- Ranked 4-10: [keywords and counts]  
- Ranked 11-50: [keywords and counts]
- Ranked 51-100: [keywords and counts]
- Ranked 100+: [keywords and counts]

### KEYWORD SEARCH VOLUME COMPARISON:
- High Volume Keywords (>5,000 searches): [complete list]
- Medium Volume Keywords (1,000-5,000 searches): [complete list]
- Low Volume Keywords (<1,000 searches): [complete list]

### SHARED VS UNIQUE KEYWORDS:
- Shared keywords between brands with search volumes
- Unique keywords per brand with search volumes

### ADDITIONAL DATA:
- Any other product/keyword metrics, rankings, revenue data, or comparisons found

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

def summarize_with_llm(text_content: str, brand_name: str, metrics: dict) -> str:
    """
    Summarize the report content using Anthropic's Claude API with entire HTML in one request.
    """
    try:
        import anthropic
        
        # Get API key from environment
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return "❌ Anthropic API key not found. Please set the ANTHROPIC_API_KEY environment variable."
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Get HTML content if available, otherwise use text_content
        if metrics.get('html_content'):
            content_to_analyze = metrics['html_content']
            content_type = "HTML"
        else:
            content_to_analyze = text_content
            content_type = "text"
        
        print(f"📊 Processing {len(content_to_analyze)} characters of {content_type} content")
        
        # Check if content is too large for single request (approx 200K token limit = ~150K characters)
        if len(content_to_analyze) > 150000:
            print("📄 Content too large, using intelligent chunking...")
            return process_with_smart_chunking(client, content_to_analyze, brand_name)
        
        # Single request for smaller content
        prompt = f"""Please analyze this complete SmartScout brand report for "{brand_name}" and create a COMPREHENSIVE PRODUCT COMPARISON ANALYSIS:

## COMPREHENSIVE PRODUCT COMPARISON ANALYSIS: {brand_name}

### MAIN BRAND PRODUCTS & KEYWORDS:
**{brand_name}:**
- List ALL product names/titles from "{brand_name}"
- For each product, list ALL keywords with search volumes
- Format: Product Name: "keyword1" (X,XXX searches), "keyword2" (X,XXX searches)

### TOP COMPETITOR BRANDS:
**Market Share Leaders:**
- List ALL competitor brands with market shares and changes
- Include brand names, percentages, and growth/decline data

### MARKET SHARE OF TOP SUBCATEGORIES:
**Category Breakdown:**
- List ALL subcategories with market share percentages
- Include category names and share changes

### TOP PRODUCT VS. TOP COMPETING PRODUCT:
**Head-to-Head Product Comparison:**
- **{brand_name} Top Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Top Competitor Product:** [name, sales rank, monthly revenue, search terms & ranks]
- **Direct Comparison Data:** [any side-by-side metrics found]

### TOP PRODUCT AND COMPETITOR SEARCHES:
**Search Term Analysis:**
- List ALL search terms with volumes for main brand products
- List ALL search terms with volumes for competitor products

### TOP KEYWORD DISTRIBUTION:
**Ranking Distribution:**
- Ranked 1-3: [keywords and counts]
- Ranked 4-10: [keywords and counts]  
- Ranked 11-50: [keywords and counts]
- Ranked 51-100: [keywords and counts]
- Ranked 100+: [keywords and counts]

### KEYWORD SEARCH VOLUME COMPARISON:
- High Volume Keywords (>5,000 searches): [complete list with volumes]
- Medium Volume Keywords (1,000-5,000 searches): [complete list with volumes] 
- Low Volume Keywords (<1,000 searches): [complete list with volumes]

### SHARED VS UNIQUE KEYWORDS:
- Shared keywords between brands: [ALL shared keywords with search volumes]
- Unique to {brand_name}: [ALL unique keywords with search volumes]
- Unique to competitors: [ALL competitor-unique keywords with search volumes]

### ADDITIONAL DATA FOUND:
- Any other relevant product/keyword data from tables, charts, or sections

Extract ALL available data. Include every detail - don't skip or summarize any information. No strategic advice needed.

Complete HTML content:
{content_to_analyze}"""
        
        try:
            response = client.messages.create(
                model="claude-sonnet-4-0",
                max_tokens=8000,
                temperature=0.3,
                messages=[{
                    "role": "user", 
                    "content": prompt
                }]
            )
            print("✅ Analysis completed in single request")
            return response.content[0].text
            
        except Exception as e:
            print(f"⚠ Error in analysis: {e}")
            return f"❌ Error generating analysis: {str(e)}"
        
    except ImportError:
        return "❌ Anthropic library not installed. Please install with: pip install anthropic"
    except Exception as e:
        return f"❌ Error generating summary: {str(e)}"

def process_brand_list(brands_input: str, action_type: str):
    """
    Process multiple brands from a comma-separated list or file.
    """
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
    
    if not brands:
        print("❌ No brands found to process")
        return
    
    print(f"🚀 Starting batch {action_type} for brands:")
    for i, brand in enumerate(brands, 1):
        print(f"  {i}. {brand}")
    print()
    
    # Process each brand and track results for collect operations
    collect_results = {"collected": [], "no_button": [], "not_found_in_search": [], "error": []} if action_type == "collect" else None
    
    for i, brand in enumerate(brands, 1):
        print(f"{'='*60}")
        print(f"Processing {i}/{len(brands)}: {brand}")
        print(f"{'='*60}")
        
        try:
            if action_type == "collect":
                result = collect_brand_data(brand, return_result=True)
                if result:
                    collect_results[result].append(brand)
            elif action_type == "download": 
                download_html_only(brand)
            elif action_type == "summary":
                summarize_html(brand)
                
            # Small delay between brands to avoid overwhelming the server
            if i < len(brands):
                print(f"\n⏳ Waiting 3 seconds before processing next brand...\n")
                time.sleep(3)
                
        except Exception as e:
            print(f"❌ Error processing {brand}: {e}")
            if action_type == "collect":
                collect_results["error"].append(brand)
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
        
        print(f"\nℹ️  No Button Found (Already Exists): {len(collect_results['no_button'])} brands") 
        if collect_results['no_button']:
            for brand in collect_results['no_button']:
                print(f"   • {brand}")
                
        print(f"\n🔍 Not Found in Search: {len(collect_results['not_found_in_search'])} brands")
        if collect_results['not_found_in_search']:
            for brand in collect_results['not_found_in_search']:
                print(f"   • {brand}")
                
        print(f"\n❌ Errors: {len(collect_results['error'])} brands")
        if collect_results['error']:
            for brand in collect_results['error']:
                print(f"   • {brand}")
                
        print(f"\n📈 Success Rate: {len(collect_results['collected'])}/{len(brands)} ({len(collect_results['collected'])/len(brands)*100:.1f}%)")
    
    print(f"{'='*60}")

def collect_brand_data(brand_name: str, return_result=False):
    """
    Look for and click 'Collect {Brand Name}'s Data Now' button without downloading report.
    """
    # Create html folder if it doesn't exist (for consistency)
    html_folder = "html"
    if not os.path.exists(html_folder):
        os.makedirs(html_folder)
        print(f"📁 Created {html_folder} folder")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, slow_mo=500)
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
                brand_selectors = [
                    f'a:has-text("{brand_name}")',
                    f'button:has-text("{brand_name}")',  
                    f'[title*="{brand_name}" i]',
                    f':text-is("{brand_name}")',
                    f':text("{brand_name}")',
                ]
                
                brand_link = None
                # Try multiple times with increasing timeouts
                found = False
                for attempt in range(3):
                    print(f"Search attempt {attempt + 1}/3...")
                    for selector in brand_selectors:
                        try:
                            brand_link = page.locator(selector).first
                            if brand_link.is_visible(timeout=3000):
                                print(f"✅ Found brand link with selector: {selector}")
                                found = True
                                break
                        except:
                            continue
                    
                    if found:  # Exit outer loop if found
                        break
                    
                    if attempt < 2:  # Don't wait after last attempt
                        print(f"⏳ Brand not found yet, waiting 2 more seconds...")
                        time.sleep(2)
                
                if brand_link and brand_link.is_visible():
                    print(f"📊 Clicking on '{brand_name}' to open brand page...")
                    brand_link.click()
                    
                    # Wait for brand page to load
                    print("⏳ Waiting for brand page to load...")
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    time.sleep(3)
                else:
                    print(f"❌ Could not find '{brand_name}' in search results")
                    result = "not_found_in_search"
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
                print(f"ℹ️  No 'Collect Data' button found for '{brand_name}'")
                print("💡 The brand report may already exist or be in progress")
                result = "no_button"
            
        except Exception as e:
            print(f"❌ An error occurred: {str(e)}")
            result = "error"
        finally:
            context.close()
        
        if return_result:
            return result

def download_html_only(brand_name: str):
    """
    Download HTML report and save to html folder without summarizing.
    """
    # Create html folder if it doesn't exist
    html_folder = "html"
    if not os.path.exists(html_folder):
        os.makedirs(html_folder)
        print(f"📁 Created {html_folder} folder")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, slow_mo=500)
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
            
            # Try to find a link or button that contains the brand name
            brand_selectors = [
                f'a:has-text("{brand_name}")',
                f'button:has-text("{brand_name}")',
                f'[title*="{brand_name}" i]',
                f'[data-brand*="{brand_name}" i]',
                f':text-is("{brand_name}")',
                f':text("{brand_name}")',
            ]
            
            brand_link = None
            for selector in brand_selectors:
                try:
                    brand_link = page.locator(selector).first
                    if brand_link.is_visible(timeout=2000):
                        print(f"Found brand report with selector: {selector}")
                        break
                except:
                    continue
            
            if not brand_link or not brand_link.is_visible():
                # Try a more general approach - look for any clickable element containing brand name
                try:
                    brand_link = page.get_by_text(brand_name, exact=False).first
                    if brand_link.is_visible(timeout=2000):
                        print("Found brand report using text search")
                except:
                    print(f"❌ Could not find brand report for '{brand_name}'")
                    print("Available reports on page:")
                    # Try to list available reports
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
                    return
            
            # 3. Click on the brand report
            print(f"📊 Opening '{brand_name}' report...")
            brand_link.click()
            
            # Wait for the report to load
            print("⏳ Waiting for report to load...")
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(5)
            
            # 4. Save HTML content
            print("💾 Saving HTML content...")
            html_content = page.content()
            html_file = os.path.join(html_folder, f"{brand_name.replace(' ', '_').lower()}_report.html")
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"📄 HTML saved as: {html_file}")
            print(f"✅ Download completed! Use --summary to generate analysis.")
            
        except Exception as e:
            print(f"❌ An error occurred: {str(e)}")
        finally:
            context.close()

def summarize_html(brand_name: str):
    """
    Generate LLM summary from existing HTML file.
    """
    html_folder = "html"
    summary_folder = "summary"
    
    # Create summary folder if it doesn't exist
    if not os.path.exists(summary_folder):
        os.makedirs(summary_folder)
        print(f"📁 Created {summary_folder} folder")
    
    # Find HTML file
    html_file = os.path.join(html_folder, f"{brand_name.replace(' ', '_').lower()}_report.html")
    
    if not os.path.exists(html_file):
        print(f"❌ HTML file not found: {html_file}")
        print(f"💡 Run 'python smartscout_downloader.py \"{brand_name}\"' first to download the report")
        return
    
    try:
        # Read HTML content
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        print(f"📄 Found HTML file: {html_file}")
        print(f"📊 Processing {len(html_content)} characters of HTML content")
        
        # Extract metrics with HTML content
        extracted_metrics = {'html_content': html_content}
        
        # Generate AI summary
        print("\n📝 Generating AI summary of the report...")
        summary = summarize_with_llm("", brand_name, extracted_metrics)
        
        # Save summary to summary folder
        summary_file = os.path.join(summary_folder, f"{brand_name.replace(' ', '_').lower()}_analysis.txt")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)
        
        print(f"📄 Summary saved to: {summary_file}")
        print("="*60)
        print("BRAND ANALYSIS:")
        print("="*60)
        print(summary)
        
    except Exception as e:
        print(f"❌ Error generating summary: {str(e)}")

def run_automation(brand_name: str):
    """
    Main function to run the browser automation.
    """
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, slow_mo=500)
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
                'input[type="text"]',
                '.search input',
                '[class*="search"] input'
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        search_input = element
                        print(f"✓ Found search input: {selector}")
                        break
                except:
                    continue
            
            if search_input:
                print(f"Searching for brand: '{brand_name}'")
                search_input.fill(brand_name)
                search_input.press("Enter")
                time.sleep(3)
            else:
                print("⚠ No search input found, looking for brand in existing reports...")
            
            # 2. Look for the brand report in the list
            print("Looking for brand report...")
            
            # Try to find the brand name in the page (could be a link or text)
            brand_selectors = [
                f'text="{brand_name}"',
                f'text=/.*{brand_name}.*/i',
                f'a:has-text("{brand_name}")',
                f'[href*="{brand_name.replace(" ", "").lower()}"]'
            ]
            
            brand_found = False
            for selector in brand_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        print(f"✓ Found brand report: {selector}")
                        element.click()
                        brand_found = True
                        break
                except:
                    continue
            
            if not brand_found:
                print("⚠ Brand report not found in the list. The report may not exist yet.")
                print("Please check if the brand report exists in SmartScout.")
            
            # 3. Wait for the report page to load
            print("Waiting for brand report page to load...")
            time.sleep(5)
            
            # Wait for network to settle
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
                print("✓ Report page loaded")
            except:
                print("⚠ Network still active (continuing anyway)")
                time.sleep(3)

            # 4. Get the full HTML content for LLM analysis
            print("\n📄 Collecting full HTML content for LLM analysis...")
            
            try:
                # Get the complete HTML content
                html_content = page.content()
                
                print(f"✅ Collected {len(html_content)} characters of HTML content")
                
                print("❌ This function is deprecated. Use download_html_only() or summarize_html() instead.")
                return
                
            except Exception as e:
                print(f"❌ This function is deprecated. Use download_html_only() or summarize_html() instead.")
                return

        except Exception as e:
            print(f"\n❌ An error occurred: {e}")
            print("Please ensure you are logged in and the brand exists.")
            print("You can try running the setup again with: python smartscout_downloader.py --setup")

        finally:
            print("Keeping browser open for inspection...")
            print("You can manually close the browser window when done.")
            # context.close()  # Commented out to keep browser open

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
    if "--setup" in sys.argv:
        setup_session()
    elif "--collect" in sys.argv:
        if len(sys.argv) > 2:
            brands_input = sys.argv[2]
            # Check if it's a list (contains comma) or file (ends with .txt/.csv)
            if ',' in brands_input or brands_input.endswith(('.txt', '.csv')):
                process_brand_list(brands_input, "collect")
            else:
                collect_brand_data(brands_input, return_result=False)
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
                process_brand_list(brands_input, "summary")
            else:
                summarize_html(brands_input)
        else:
            print("❌ Brand name(s) required for --summary option")
            print("Usage: python smartscout_downloader.py --summary \"Brand Name\"")
            print("   or: python smartscout_downloader.py --summary \"Brand1, Brand2, Brand3\"")
            print("   or: python smartscout_downloader.py --summary brands.txt")
            sys.exit(1)
    elif len(sys.argv) > 1:
        brands_input = sys.argv[1]
        # Check if it's a list (contains comma) or file (ends with .txt/.csv)
        if ',' in brands_input or brands_input.endswith(('.txt', '.csv')):
            process_brand_list(brands_input, "download")
        else:
            download_html_only(brands_input)
    else:
        print("Usage:")
        print("  For first-time setup (to log in):")
        print("    python smartscout_downloader.py --setup")
        print("\n  To trigger data collection for brand(s):")
        print("    python smartscout_downloader.py --collect \"Brand Name\"")
        print("    python smartscout_downloader.py --collect \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_downloader.py --collect brands.txt")
        print("\n  To download brand report(s):")
        print("    python smartscout_downloader.py \"Brand Name\"")
        print("    python smartscout_downloader.py \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_downloader.py brands.txt")
        print("\n  To generate AI summary from existing HTML:")
        print("    python smartscout_downloader.py --summary \"Brand Name\"")
        print("    python smartscout_downloader.py --summary \"Brand1, Brand2, Brand3\"")
        print("    python smartscout_downloader.py --summary brands.txt")
        sys.exit(1)
