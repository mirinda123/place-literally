# Place, Literally

A map of what place names mean. Click a place to see its literal meaning and find other places with similar meanings.

## Run locally

You need Node.js 22.13+, Python 3.11+, and Elasticsearch 9.x. Set up the database and Python dependencies using the [backend guide](backend/README.md), then start the API:

```sh
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start the frontend:

```sh
npm ci
npm run dev
```

Open http://localhost:5173/. The full Elasticsearch dataset is not included in this repository.

## Checks

Run `npm test` for frontend tests and `npm run build` to build the app.

## License

Code is licensed under [MIT](LICENSE). See [third-party notices](THIRD_PARTY.md) for map and data licenses.
