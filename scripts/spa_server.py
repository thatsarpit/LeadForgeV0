#!/usr/bin/env python3
"""
Simple HTTP server for serving Single Page Applications.
Serves index.html for all routes (SPA routing).
"""
import http.server
import socketserver
from pathlib import Path

class SPAHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that serves index.html for all routes."""
    
    def end_headers(self):
        # Add CORS headers for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_GET(self):
        # Serve index.html for root path
        if self.path == '/':
            self.path = '/index.html'
        
        # If file doesn't exist, serve index.html (SPA routing)
        file_path = Path(self.translate_path(self.path))
        if not file_path.exists() or file_path.is_dir():
            self.path = '/index.html'
        
        return super().do_GET()

if __name__ == '__main__':
    PORT = 5173
    Handler = SPAHTTPRequestHandler
    
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving SPA on http://0.0.0.0:{PORT}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
