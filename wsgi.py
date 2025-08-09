from app import create_app

app = create_app()

if __name__ == "__main__":
    # Run with built-in server for simplicity in Docker; can switch to gunicorn in production
    app.run(host="0.0.0.0", port=5000)
