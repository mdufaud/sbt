#!/usr/bin/env python3
"""HTTP server with CORS headers for WebAssembly with SharedArrayBuffer support."""

import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class CORSRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with CORS headers for SharedArrayBuffer."""

    def end_headers(self):
        """Add CORS headers required for SharedArrayBuffer."""
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()


def main():
    """Run HTTP server with CORS headers."""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    directory = sys.argv[2] if len(sys.argv) > 2 else '.'
    
    # Change to the specified directory
    if directory != '.':
        import os
        os.chdir(directory)
    
    server = HTTPServer(('', port), CORSRequestHandler)
    print(f"Serving HTTP on http://0.0.0.0:{port} from {Path(directory).resolve()}")
    print(f"With CORS headers for SharedArrayBuffer support")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == '__main__':
    main()
