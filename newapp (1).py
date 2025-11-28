import streamlit as st
import pandas as pd
import requests
import json
from typing import List
import plotly.express as px

# FastAPI backend URL
API_BASE_URL = "http://localhost:8000"

def load_urls_from_json(file_content):
    """Load URLs from JSON file content"""
    try:
        data = json.loads(file_content)
        urls = []
        for item in data:
            if isinstance(item, dict) and 'name' in item:
                urls.append(item['name'])
        return urls
    except Exception as e:
        st.error(f"Error loading JSON: {e}")
        return []

def analyze_with_api(urls: List[str]):
    """Send URLs to FastAPI for analysis"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/analyze",
            json={"urls": urls}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        return None

def display_analysis_results(result):
    """Display analysis results"""
    if not result:
        st.error("No analysis results to display")
        return
        
    # Extract the actual data from the response
    analysis_data = result.get('analysis', {})
    data = result.get('data', {})
    
    st.subheader("📊 Analysis Summary")
    
    # Display summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total URIs", analysis_data.get('totalUris', 0))
    with col2:
        st.metric("Unique Patterns", analysis_data.get('uniquePatterns', 0))
    with col3:
        st.metric("Pattern Compression", f"{analysis_data.get('patternCompression', 0)}%")
    
    # Display patterns hierarchy
    st.subheader("🔍 Pattern Hierarchy")
    
    if not data:
        st.info("No patterns found in the analysis")
        return
        
    for parent_pattern, entries in data.items():
        with st.expander(f"Parent Pattern: `{parent_pattern}` ({len(entries)} variants)"):
            for entry in entries:
                st.write(f"**URI Pattern:** `{entry.get('uri', '')}`")
                sub_patterns = entry.get('subPatterns', [])
                if sub_patterns:
                    st.write("**Sub-Patterns:**")
                    for sub_pattern in sub_patterns:
                        st.write(f"- `{sub_pattern}`")
                else:
                    st.write("**No specific sub-patterns found**")
                st.write("---")
    
    # Display statistics
    st.subheader("📈 Pattern Statistics")
    
    # Calculate pattern counts
    pattern_counts = []
    for parent_pattern, entries in data.items():
        for entry in entries:
            pattern_counts.append({
                'Pattern': entry.get('uri', ''),
                'SubPatterns Count': len(entry.get('subPatterns', [])),
                'Type': 'URI Pattern'
            })
            for sub_pattern in entry.get('subPatterns', []):
                pattern_counts.append({
                    'Pattern': sub_pattern,
                    'SubPatterns Count': 0,
                    'Type': 'Sub-Pattern'
                })
    
    if pattern_counts:
        patterns_df = pd.DataFrame(pattern_counts)
        
        # Show pattern types distribution
        type_counts = patterns_df['Type'].value_counts()
        if not type_counts.empty:
            fig_types = px.pie(
                values=type_counts.values,
                names=type_counts.index,
                title="Pattern Types Distribution"
            )
            st.plotly_chart(fig_types, use_container_width=True)
        
        # Show top patterns by sub-pattern count
        uri_patterns = patterns_df[patterns_df['Type'] == 'URI Pattern']
        if not uri_patterns.empty:
            top_patterns = uri_patterns.nlargest(10, 'SubPatterns Count')
            fig_patterns = px.bar(
                top_patterns,
                x='SubPatterns Count',
                y='Pattern',
                orientation='h',
                title="Top 10 URI Patterns by Number of Sub-Patterns"
            )
            fig_patterns.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig_patterns, use_container_width=True)

def main():
    st.set_page_config(
        page_title="URL Pattern Analyzer",
        page_icon="🔗",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🔗 URL Pattern Analyzer")
    st.markdown("Analyze and cluster URLs to identify API patterns and endpoints with sub-pattern detection")
    
    # Sidebar for input
    st.sidebar.header("Input Options")
    
    input_method = st.sidebar.radio(
        "Choose input method:",
        ["Upload JSON File", "Paste URLs"]
    )
    
    urls = []
    
    if input_method == "Upload JSON File":
        uploaded_file = st.sidebar.file_uploader(
            "Upload JSON file with URLs",
            type=['json'],
            help="JSON file should contain objects with 'name' field containing URLs"
        )
        
        if uploaded_file is not None:
            file_content = uploaded_file.getvalue().decode('utf-8')
            urls = load_urls_from_json(file_content)
            st.sidebar.success(f"Loaded {len(urls)} URLs from file")
    
    else:  # Paste URLs
        url_text = st.sidebar.text_area(
            "Paste URLs (one per line):",
            height=200,
            help="Enter URLs in format: 'GET https://example.com/api/endpoint' or just the URL"
        )
        
        if url_text:
            urls = [line.strip() for line in url_text.split('\n') if line.strip()]
            st.sidebar.success(f"Loaded {len(urls)} URLs")
    
    # API status check
    try:
        health_response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if health_response.status_code == 200:
            st.sidebar.success("✅ API Connected")
        else:
            st.sidebar.error("❌ API Connection Failed")
    except:
        st.sidebar.error("❌ Cannot connect to API")
        st.sidebar.info(f"Make sure the FastAPI server is running at {API_BASE_URL}")
    
    if urls:
        st.header("Analysis Results")
        
        # Perform analysis via API
        with st.spinner("Analyzing URLs and detecting patterns..."):
            analysis_result = analyze_with_api(urls)
        
        if analysis_result is None:
            st.error("Failed to analyze URLs. Please check the API connection.")
            return
        
        # Display analysis results
        display_analysis_results(analysis_result)
        
        # Download results
        st.subheader("💾 Download Results")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Download as JSON
            json_data = json.dumps(analysis_result, indent=2)
            st.download_button(
                label="Download Analysis JSON",
                data=json_data,
                file_name="url_pattern_analysis.json",
                mime="application/json"
            )
        
        with col2:
            # Create simplified CSV for patterns
            pattern_data = []
            data = analysis_result.get('data', {})
            for parent_pattern, entries in data.items():
                for entry in entries:
                    pattern_data.append({
                        'Parent Pattern': parent_pattern,
                        'URI Pattern': entry.get('uri', ''),
                        'SubPatterns Count': len(entry.get('subPatterns', [])),
                        'SubPatterns': ' | '.join(entry.get('subPatterns', []))
                    })
            
            if pattern_data:
                patterns_df = pd.DataFrame(pattern_data)
                csv_data = patterns_df.to_csv(index=False)
                st.download_button(
                    label="Download Patterns CSV",
                    data=csv_data,
                    file_name="url_patterns.csv",
                    mime="text/csv"
                )
    
    else:
        st.info("👆 Please upload a JSON file or paste URLs in the sidebar to get started.")
        
        # Show example
        st.subheader("Example Input Format")
        st.code("""[
    {
        "name": "GET https://api.example.com/services/users/12345 HTTP/1.1"
    },
    {
        "name": "POST https://api.example.com/services/users HTTP/1.1"
    },
    {
        "name": "GET https://api.example.com/services/users/67890/profile HTTP/1.1"
    }
]""", language="json")
        
        # Show expected output format
        st.subheader("Expected Output Format")
        st.code("""{
  "analysis": {
    "totalUris": 500,
    "uniquePatterns": 322,
    "patternCompression": 35.6
  },
  "data": {
    "GET https://wm-sandbox-1\\.watermelon\\.us:443/api/sts/grant-token?source=(.*?)&destination=(.*?)": [
      {
        "uri": "GET https://wm-sandbox-1\\.watermelon\\.us:443/api/sts/grant-token?source=WMProject&destination=(.*?)",
        "subPatterns": [
          "GET https://wm-sandbox-1\\.watermelon\\.us:443/api/sts/grant-token?source=WMProject&destination=UserData",
          "GET https://wm-sandbox-1\\.watermelon\\.us:443/api/sts/grant-token?source=WMProject&destination=Analytics"
        ]
      }
    ]
  }
}""", language="json")

if __name__ == "__main__":
    main()