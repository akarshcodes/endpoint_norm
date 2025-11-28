from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import uvicorn
from urllib.parse import urlparse, parse_qs, unquote
import re
from collections import defaultdict, Counter
import json

app = FastAPI(
    title="URL Pattern Analyzer API",
    description="API for analyzing and clustering URL patterns with sub-pattern detection",
    version="2.5.0"
)

class URLAnalyzer:
    def __init__(self):
        # Remove forward slash from special characters that need escaping
        self.special_chars = ['.', '^', '$', '*', '+', '?', '{', '}', '[', ']', '\\', '|', '(', ')']
        
    def escape_special_chars_for_pattern(self, text: str) -> str:
        """Escape special characters for regex patterns, but preserve (.*?) wildcards"""
        if not text:
            return text
            
        # First, protect existing wildcards
        protected_text = text.replace('(.*?)', '___WILDCARD___')
        
        # Escape special characters (except forward slash)
        for char in self.special_chars:
            protected_text = protected_text.replace(char, f'\\{char}')
        
        # Restore wildcards
        protected_text = protected_text.replace('___WILDCARD___', '(.*?)')
        return protected_text
    
    def extract_http_method(self, url_string: str) -> tuple[str, str]:
        """Extract HTTP method from URL string"""
        method = ""
        clean_url = url_string.strip()
        
        # Remove quotes if present
        clean_url = clean_url.strip('"')
        
        http_match = re.match(
            r'^(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+(https?://\S+)(?:\s+HTTP/\d\.\d)?$',
            clean_url
        )
        if http_match:
            method = http_match.group(1)
            clean_url = http_match.group(2)
        
        return method, clean_url
    
    def should_normalize_segment(self, segment: str) -> bool:
        """Check if a path segment should be normalized to wildcard"""
        # UUID pattern
        if re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', segment, re.IGNORECASE):
            return True
        
        # Hex strings (like in JS/CSS files)
        if re.fullmatch(r'[a-f0-9]{12,}', segment, re.IGNORECASE):
            return True
            
        # Long numeric IDs
        if segment.isdigit() and len(segment) > 5:
            return True
            
        # Mixed alphanumeric with specific patterns (like in asset files)
        if re.search(r'[a-f0-9]{8,}', segment, re.IGNORECASE) and len(segment) > 10:
            return True
            
        return False
    
    def normalize_url_pattern(self, url: str, aggressive_normalization: bool = False, escape_special_chars: bool = False) -> str:
        """Normalize URL to create pattern with (.*?) for dynamic parts"""
        method, clean_url = self.extract_http_method(url)
        
        try:
            parsed = urlparse(clean_url)
            
            # Handle scheme and netloc - escape if needed
            if escape_special_chars:
                scheme = self.escape_special_chars_for_pattern(parsed.scheme)
                netloc = self.escape_special_chars_for_pattern(parsed.netloc)
            else:
                scheme = parsed.scheme
                netloc = parsed.netloc
            
            path = parsed.path
            query = parsed.query
            
            # Normalize path segments
            path_segments = [seg for seg in path.split('/') if seg]
            normalized_path_segments = []
            
            for segment in path_segments:
                if self.should_normalize_segment(segment):
                    normalized_path_segments.append('(.*?)')
                elif aggressive_normalization and (any(char.isdigit() for char in segment) and len(segment) > 8):
                    parts = re.split(r'[_\-. ]', segment)
                    if any(part.isdigit() and len(part) > 3 for part in parts):
                        normalized_path_segments.append('(.*?)')
                    else:
                        if escape_special_chars:
                            normalized_path_segments.append(self.escape_special_chars_for_pattern(segment))
                        else:
                            normalized_path_segments.append(segment)
                else:
                    if escape_special_chars:
                        normalized_path_segments.append(self.escape_special_chars_for_pattern(segment))
                    else:
                        normalized_path_segments.append(segment)
            
            # Build path - NO escaping of forward slashes
            normalized_path = '/' + '/'.join(normalized_path_segments)
            
            # Normalize query parameters
            normalized_query_parts = []
            if query:
                # URL decode the query string first
                decoded_query = unquote(query)
                query_params = parse_qs(decoded_query)
                
                for key, values in query_params.items():
                    if escape_special_chars:
                        escaped_key = self.escape_special_chars_for_pattern(key)
                    else:
                        escaped_key = key
                    
                    for value in values:
                        # Check if value should be normalized
                        if aggressive_normalization and (value.isdigit() or 
                            re.fullmatch(r'[a-f0-9-]{12,}', value, re.IGNORECASE) or
                            len(value) > 15 or
                            self.should_normalize_segment(value)):
                            normalized_query_parts.append(f"{escaped_key}=(.*?)")
                        else:
                            if escape_special_chars:
                                escaped_value = self.escape_special_chars_for_pattern(value)
                            else:
                                escaped_value = value
                            normalized_query_parts.append(f"{escaped_key}={escaped_value}")
            
            normalized_query = '&'.join(normalized_query_parts)
            
            # Build the normalized URL properly
            normalized_url = f"{scheme}://{netloc}{normalized_path}"
            if normalized_query:
                # For patterns, escape the ? that separates path from query
                if escape_special_chars:
                    normalized_url += f"\\?{normalized_query}"
                else:
                    normalized_url += f"?{normalized_query}"
            
            if method:
                normalized_url = f"{method} {normalized_url}"
                
            return normalized_url
            
        except Exception as e:
            print(f"Error normalizing URL {url}: {e}")
            if escape_special_chars:
                return self.escape_special_chars_for_pattern(url)
            return url
    
    def is_sub_pattern_of(self, candidate: str, parent: str) -> bool:
        """Check if candidate is a sub-pattern of parent"""
        if candidate == parent:
            return False
            
        # Count wildcards - sub-pattern should have same or fewer wildcards
        parent_wildcards = parent.count('(.*?)')
        candidate_wildcards = candidate.count('(.*?)')
        
        if candidate_wildcards > parent_wildcards:
            return False
        
        # Convert patterns to comparable strings by replacing wildcards with a placeholder
        parent_compare = parent.replace('(.*?)', '___WILDCARD___')
        candidate_compare = candidate.replace('(.*?)', '___WILDCARD___')
        
        # For sub-pattern relationship, the structure should be similar
        # but candidate should have more specific values where parent has wildcards
        parent_parts = re.split(r'(\?|&|=)', parent_compare)
        candidate_parts = re.split(r'(\?|&|=)', candidate_compare)
        
        if len(parent_parts) != len(candidate_parts):
            return False
            
        for p_part, c_part in zip(parent_parts, candidate_parts):
            if p_part == '___WILDCARD___':
                # Parent has wildcard here, candidate can have anything
                continue
            elif p_part != c_part:
                return False
                
        return True
    
    def find_subpatterns_in_matching_urls(self, urls: List[str], parent_pattern: str) -> List[Dict[str, Any]]:
        """Find subpatterns within URLs that match the same parent pattern"""
        if len(urls) <= 1:
            # If only one URL, return the actual URL as URI (not pattern)
            return [{"uri": urls[0], "subPatterns": [], "count": 1}]
        
        # Group URLs by their less aggressive normalization (without escaping for URIs)
        sub_pattern_groups = defaultdict(list)
        for url in urls:
            sub_pattern = self.normalize_url_pattern(url, aggressive_normalization=False, escape_special_chars=False)
            sub_pattern_groups[sub_pattern].append(url)
        
        # If all URLs have the same sub-pattern, check if we need to split further
        if len(sub_pattern_groups) == 1:
            sub_pattern = list(sub_pattern_groups.keys())[0]
            pattern_urls = sub_pattern_groups[sub_pattern]
            
            # Remove escaping from parent pattern for comparison
            parent_pattern_clean = parent_pattern.replace('\\', '')
            
            # If the sub-pattern is the same as parent pattern, show actual URLs
            if sub_pattern == parent_pattern_clean or len(pattern_urls) == 1:
                return [{"uri": url, "subPatterns": [], "count": 1} for url in pattern_urls]
            else:
                return [{"uri": sub_pattern, "subPatterns": [], "count": len(pattern_urls)}]
        
        # Organize hierarchically
        organized_subpatterns = []
        all_sub_patterns = list(sub_pattern_groups.keys())
        
        for sub_pattern in all_sub_patterns:
            # Find URLs for this sub-pattern
            pattern_urls = sub_pattern_groups[sub_pattern]
            
            # Remove escaping from parent pattern for comparison
            parent_pattern_clean = parent_pattern.replace('\\', '')
            
            # If sub-pattern is too generic (same as parent), show actual URLs
            if sub_pattern == parent_pattern_clean or len(pattern_urls) == 1:
                organized_subpatterns.extend([{"uri": url, "subPatterns": [], "count": 1} for url in pattern_urls])
            else:
                organized_subpatterns.append({
                    "uri": sub_pattern,
                    "subPatterns": [],
                    "count": len(pattern_urls)
                })
        
        return organized_subpatterns
    
    def analyze_urls_with_subpatterns(self, urls: List[str]) -> Dict[str, Any]:
        """Analyze URLs and return in the standard JSON format with sub-patterns"""
        if not urls:
            return {
                "analysis": {"totalUris": 0, "uniquePatterns": 0, "patternCompression": 0},
                "data": {}
            }
        
        # Step 1: Create aggressive patterns (parent patterns) WITH escaping
        aggressive_patterns = {}
        for url in urls:
            parent_pattern = self.normalize_url_pattern(url, aggressive_normalization=True, escape_special_chars=True)
            if parent_pattern not in aggressive_patterns:
                aggressive_patterns[parent_pattern] = []
            aggressive_patterns[parent_pattern].append(url)
        
        # Step 2: Build the result structure with proper sub-pattern detection
        data = {}
        
        for parent_pattern, parent_urls in aggressive_patterns.items():
            # Find subpatterns within matching URLs (without escaping for URIs)
            organized_subpatterns = self.find_subpatterns_in_matching_urls(parent_urls, parent_pattern)
            
            data[parent_pattern] = organized_subpatterns
        
        # Step 3: Calculate metrics
        total_uris = len(urls)
        
        all_patterns = set()
        for parent_pattern, entries in data.items():
            all_patterns.add(parent_pattern)
            for entry in entries:
                # For URI entries, use them as-is; for pattern entries, count them
                if '(.*?)' in entry["uri"] or any(char in entry["uri"] for char in self.special_chars if char not in ['/', ':']):
                    all_patterns.add(entry["uri"])
                all_patterns.update(entry["subPatterns"])
        
        total_unique_patterns = len(all_patterns)
        pattern_compression = round((1 - total_unique_patterns / total_uris) * 100, 1) if total_uris > 0 else 0
        
        analysis = {
            "totalUris": total_uris,
            "uniquePatterns": total_unique_patterns,
            "patternCompression": pattern_compression
        }
        
        return {
            "analysis": analysis,
            "data": data
        }

# Pydantic models for request/response
class AnalysisRequest(BaseModel):
    urls: List[str]
    options: Optional[Dict] = {}

class AnalysisResponse(BaseModel):
    analysis: Dict[str, Any]
    data: Dict[str, Any]

# Initialize analyzer
analyzer = URLAnalyzer()

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_urls(request: AnalysisRequest):
    """Analyze URLs and return patterns in standard JSON format"""
    try:
        result = analyzer.analyze_urls_with_subpatterns(request.urls)
        return AnalysisResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "URL Pattern Analyzer API"}

if __name__ == "__main__":
    uvicorn.run("yoback5:app", host="0.0.0.0", port=8000, reload=True)