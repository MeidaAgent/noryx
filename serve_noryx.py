from backend_server import (
    NoryxHandler,
    ThreadingHTTPServer,
    init_database,
    start_pons_indexer,
)


if __name__ == "__main__":
    init_database()
    start_pons_indexer()
    print("Noryx backend berjalan di http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), NoryxHandler).serve_forever()
