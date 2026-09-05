from desk.server import app

__all__ = ["app"]


def main() -> None:
    import uvicorn

    uvicorn.run("desk.server:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
