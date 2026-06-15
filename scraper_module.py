import asyncio
import pandas as pd
import re
from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncStealthySession

class RealEstateAgentSpider(Spider):
    name = "real_estate_agents"
    
    # Speed Optimizations
    concurrent_requests = 5  # Reduced to 5 to prevent overwhelming local CPU with headless browsers
    download_delay = 0.5     
    
    def __init__(self, location, max_pages=3, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = location
        self.max_pages = int(max_pages)
        # Normalize location for Zillow (hyphen) and Realtor (underscore)
        loc_slug = location.lower().replace(", ", "-").replace(" ", "-")
        zillow_loc = loc_slug
        # Realtor usually uses city_state-id or similar, but city_state is a good start
        realtor_loc = loc_slug.replace("-", "_") if "-" in loc_slug else loc_slug
        
        self.start_urls = [
            f"https://www.zillow.com/professionals/real-estate-agent-reviews/{zillow_loc}/",
            f"https://www.realtor.com/realestateagents/{realtor_loc}"
        ]
        self.results = []
        self.seen_urls = set()

    def configure_sessions(self, manager):
        # Increased timeout and added stealth
        manager.add("stealth", AsyncStealthySession(
            headless=True, 
            solve_cloudflare=True,
            timeout=45000 # 45 seconds
        ))

    async def parse(self, response: Response):
        print(f"Parsing list page: {response.url}")
        
        if "zillow.com" in response.url:
            # Extract current page from URL
            current_page = 1
            if "page=" in response.url:
                try:
                    current_page = int(response.url.split("page=")[-1].split("&")[0])
                except:
                    pass
            
            # More aggressive link discovery for Zillow
            agent_links = response.css('a[href*="/profile/"]::attr(href)').getall()
            found_new = False
            for link in agent_links:
                profile_url = response.urljoin(link)
                if "/profile/" in profile_url and profile_url not in self.seen_urls:
                    if any(x in profile_url.lower() for x in ["/profile/remax", "/profile/team", "profile"]):
                        self.seen_urls.add(profile_url)
                        found_new = True
                        yield Request(profile_url, sid="stealth", callback=self.parse_profile)
            
            # Zillow Pagination - Explicit URL Construction if we found agents
            if found_new and current_page < self.max_pages:
                next_page_url = f"https://www.zillow.com/professionals/real-estate-agent-reviews/{self.location.lower().replace(', ', '-').replace(' ', '-')}/?page={current_page + 1}"
                yield Request(next_page_url, sid="stealth", callback=self.parse)

        elif "realtor.com" in response.url:
            current_page = 1
            if "/pg-" in response.url:
                try:
                    current_page = int(response.url.split("/pg-")[-1].split("/")[0])
                except:
                    pass
                    
            agent_links = response.css('a[href*="/realestateagents/"]::attr(href)').getall()
            found_new = False
            for link in agent_links:
                profile_url = response.urljoin(link)
                if "_" in profile_url.split("/")[-1] and profile_url not in self.seen_urls:
                    self.seen_urls.add(profile_url)
                    found_new = True
                    yield Request(profile_url, sid="stealth", callback=self.parse_profile)
            
            if found_new and current_page < self.max_pages:
                realtor_loc = self.location.lower().replace(", ", "-").replace(" ", "-")
                realtor_loc = realtor_loc.replace("-", "_") if "-" in realtor_loc else realtor_loc
                next_page_url = f"https://www.realtor.com/realestateagents/{realtor_loc}/pg-{current_page + 1}"
                yield Request(next_page_url, sid="stealth", callback=self.parse)

    async def parse_profile(self, response: Response):
        print(f"Parsing profile: {response.url}")
        item = {
            "source": "Unknown",
            "name": "",
            "phone": "",
            "email": "",
            "website": "",
            "agency": "",
            "sales_last_12mo": "",
            "total_sales": "",
            "experience": "",
            "price_range": "",
            "recent_sales_count_6mo": 0,
            "recent_sales_volume_6mo": 0,
            "address": "",
            "url": response.url
        }
        
        page_text = response.text
        
        # Fallback Email Extraction using Regex
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', page_text)
        if emails:
            # Filter out common junk emails
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'sentry.io', 'zillow', 'realtor'])]
            if valid_emails:
                item["email"] = valid_emails[0]

        if "zillow.com" in response.url:
            item["source"] = "Zillow"
            item["name"] = (response.css('h1::text').get() or "").strip()
            item["phone"] = (response.css('a[href^="tel:"]::text').get() or "").strip()
            
            if not item["email"]:
                item["email"] = (response.css('a[href^="mailto:"]::text').get() or "").strip()
            
            # Website - look for "Visit website" or similar
            website = response.css('a:contains("Visit")::attr(href)').get() or \
                      response.css('a[data-za-label="Visit website"]::attr(href)').get()
            if website and "zillow.com" not in website:
                item["website"] = website
            
            item["agency"] = (response.css('.profile-header-business-name::text').get() or \
                             response.css('.business-name::text').get() or \
                             response.xpath('//div[contains(@class, "business-info")]//b/text()').get() or "").strip()
            
            # Stats
            for li in response.css('div.profile-information-summary li, div.profile-stats li, .profile-stats-row'):
                text = li.get_all_text().lower()
                val = li.css('strong::text, b::text, .value::text').get()
                if val:
                    if 'sales last 12 months' in text: item['sales_last_12mo'] = val
                    elif 'total sales' in text: item['total_sales'] = val
                    elif 'experience' in text: item['experience'] = val
                    elif 'price range' in text: item['price_range'] = val

            # Address
            addr = response.css('.profile-header-address::text').get() or \
                   response.xpath('//a[contains(@href, "maps.google.com")]/text()').get()
            item["address"] = addr.strip() if addr else ""

            # 6-month sales logic
            sales_items = response.css('div#recent-sales-list li, .past-sales-row, .sales-history-row')
            for sale in sales_items:
                sale_text = sale.get_all_text().lower()
                is_recent = False
                if any(x in sale_text for x in ['days ago', 'month ago', '1 month ago']):
                    is_recent = True
                else:
                    for i in range(2, 7):
                        if f'{i} months ago' in sale_text:
                            is_recent = True
                            break
                
                if is_recent:
                    item["recent_sales_count_6mo"] += 1
                    price_str = sale.css('span:contains("$")::text, .price::text').get()
                    if price_str:
                        try:
                            # Extract number from "$1,234,567"
                            price = int(re.sub(r'[^\d]', '', price_str))
                            item["recent_sales_volume_6mo"] += price
                        except: pass

        elif "realtor.com" in response.url:
            item["source"] = "Realtor.com"
            item["name"] = (response.css('h1[data-testid="agent-name"]::text').get() or response.css('h1::text').get() or "").strip()
            item["phone"] = (response.css('a[data-testid="phone-link"]::text').get() or response.css('a[href^="tel:"]::text').get() or "").strip()
            item["agency"] = (response.css('div[data-testid="agent-broker-name"]::text').get() or "").strip()
            
            # Realtor Website
            item["website"] = response.css('a[data-testid="agent-website"]::attr(href)').get() or ""
            
            # Stats
            exp = response.css('span[data-testid="experience-label"]::text').get()
            if exp: item["experience"] = exp
            
            activity = response.css('div[data-testid="agent-activity"] span::text').getall()
            if activity:
                item["sales_last_12mo"] = ", ".join(activity)

        if item.get("name"):
            self.results.append(item)
            yield item

def run_scraper(location, max_pages=3):
    print(f"Running scraper for: {location} (Max Pages: {max_pages})")
    spider = RealEstateAgentSpider(location=location, max_pages=max_pages)
    # Scrapling start() is blocking but efficient for this use case
    result = spider.start()
    
    if not result.items:
        print("No items found.")
        return None
        
    print(f"Scraped {len(result.items)} agents.")
    df = pd.DataFrame(result.items)
    
    # Ensure all requested columns exist
    cols = ["source", "name", "phone", "email", "website", "agency", "sales_last_12mo", "total_sales", "experience", "price_range", "recent_sales_count_6mo", "recent_sales_volume_6mo", "address", "url"]
    for col in cols:
        if col not in df.columns:
            df[col] = ""
            
    df = df[cols]
    
    csv_file = f"scraped_agents_{location.replace(' ', '_').replace(',', '')}.csv"
    df.to_csv(csv_file, index=False)
    print(f"Saved to: {csv_file}")
    return csv_file
