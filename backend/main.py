from contextlib import asynccontextmanager
from typing import Annotated

from elastic_transport import TransportError
from elasticsearch import ApiError, NotFoundError
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, connect
from .feedback import FeedbackRequest, build_feedback_document, save_feedback
from .indexing import PUBLIC_SOURCE_EXCLUDES
from .search import SearchRequest, run_search
from .similar import SimilarLanguage, similar_places
from .vector_similar import QueryEmbeddingService, vector_similar_places


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.es = connect(settings)
        app.state.query_embeddings = QueryEmbeddingService()
        try:
            yield
        finally:
            app.state.es.close()

    app = FastAPI(title="Place, Literally API", version="0.2.0", lifespan=lifespan,
                  description="地理实体与多语言字面含义；反馈单独保存，不修改 features 索引。")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(ApiError)
    @app.exception_handler(TransportError)
    async def es_error(request, exc):
        return JSONResponse(status_code=503, content={
            "detail": "数据服务暂不可用，请检查 Elasticsearch 连接和 features 索引。"})

    @app.get("/health")
    def health(request: Request):
        client = request.app.state.es
        info = client.info()
        mapping = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
        return {"status": "ok", "elasticsearch_version": info["version"]["number"],
                "index": settings.index, "features": client.count(index=settings.index)["count"],
                "analyzer": mapping.get("_meta", {}).get("analyzer")}

    @app.get("/api/search")
    def search_get(request: Request, params: Annotated[SearchRequest, Query()]):
        return run_search(request.app.state.es, settings, params)

    @app.post("/api/search")
    def search_post(request: Request, params: SearchRequest):
        return run_search(request.app.state.es, settings, params)

    @app.post("/api/feedback", status_code=201)
    def submit_feedback(request: Request, report: FeedbackRequest):
        client = request.app.state.es
        feature = get_feature(client, report.feature_id)
        try:
            document = build_feedback_document(feature, report)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        save_feedback(client, settings.feedback_index, document)
        return {"id": document["id"], "status": document["status"]}

    @app.get("/api/features")
    def features(request: Request, limit: int = Query(20, ge=1, le=100),
                 offset: int = Query(0, ge=0, le=9900),
                 meaning_id: str | None = Query(None, max_length=100),
                 kind: str | None = Query(None, max_length=40)):
        filters = [{"term": {key: val}} for key, val in (("meaning_id", meaning_id), ("kind", kind)) if val]
        found = request.app.state.es.search(
            index=settings.index, query={"bool": {"filter": filters}} if filters else {"match_all": {}},
            size=limit, from_=offset, sort=[{"feature_id": "asc"}], track_total_hits=True,
            source_excludes=PUBLIC_SOURCE_EXCLUDES)
        return {"total": found["hits"]["total"]["value"], "offset": offset, "limit": limit,
                "results": [hit["_source"] for hit in found["hits"]["hits"]]}

    def get_feature(client, feature_id, include_vectors=False):
        try:
            source_options = ({"source_exclude_vectors": False} if include_vectors else
                              {"source_excludes": PUBLIC_SOURCE_EXCLUDES})
            return client.get(index=settings.index, id=feature_id,
                              **source_options)["_source"]
        except NotFoundError as exc:
            if exc.body.get("error", {}).get("type") == "index_not_found_exception":
                raise
            raise HTTPException(404, "未收录该地点") from exc

    @app.get("/api/map-features")
    def map_features(request: Request, limit: int = Query(1000, ge=1, le=1000),
                     after: str | None = Query(None, min_length=1, max_length=200)):
        # The map needs its supported display languages; full names stay available
        # through detail, resolve and search endpoints.
        found = request.app.state.es.search(index=settings.index, size=limit,
            query={"match_all": {}}, sort=[{"feature_id": "asc"}], track_total_hits=True,
            search_after=[after] if after else None,
            source_excludes=PUBLIC_SOURCE_EXCLUDES,
            source_includes=["feature_id", "kind", "names.en", "names.zh*", "names.es", "names.fr",
                             "names.ja", "names.ko", "names.und", "location", "literal_name",
                             "literal_meanings", "meaning_id", "external_ids"])
        hits = found["hits"]["hits"]
        return {"total": found["hits"]["total"]["value"], "results": [h["_source"] for h in hits],
                "next_after": hits[-1]["sort"][0] if len(hits) == limit else None}

    @app.get("/api/features/resolve")
    def resolve_feature(request: Request, osm: str = Query(
            ..., pattern=r"^(node|way|relation)/[1-9][0-9]{0,18}$")):
        found = request.app.state.es.search(index=settings.index,
            query={"term": {"external_ids.osm": osm}}, size=2, track_total_hits=True,
            source_excludes=PUBLIC_SOURCE_EXCLUDES)
        total = found["hits"]["total"]["value"]
        # Never silently choose between two documents claiming the same identity.
        return {"osm": osm, "status": "matched" if total == 1 else "not_found" if total == 0 else "ambiguous",
                "feature": found["hits"]["hits"][0]["_source"] if total == 1 else None}

    @app.get("/api/features/{feature_id}")
    def feature(request: Request, feature_id: str):
        return get_feature(request.app.state.es, feature_id)

    @app.get("/api/features/{feature_id}/related")
    def related(request: Request, feature_id: str, limit: int = Query(20, ge=1, le=100),
                offset: int = Query(0, ge=0, le=9900)):
        client = request.app.state.es
        doc = get_feature(client, feature_id)
        response = {"meaning_id": doc["meaning_id"], "relation": "same_meaning",
                    "total": 0, "offset": offset, "limit": limit, "results": []}
        if not doc["meaning_id"]:
            return response
        found = client.search(index=settings.index, query={"bool": {
            "filter": [{"term": {"meaning_id": doc["meaning_id"]}}],
            "must_not": [{"term": {"feature_id": feature_id}}],
        }}, size=limit, from_=offset, sort=[{"feature_id": "asc"}], track_total_hits=True,
            source_excludes=PUBLIC_SOURCE_EXCLUDES)
        response.update(total=found["hits"]["total"]["value"],
                        results=[hit["_source"] for hit in found["hits"]["hits"]])
        return response

    @app.get("/api/features/{feature_id}/similar")
    def similar(request: Request, feature_id: str,
                lang: SimilarLanguage = Query("zh")):
        client = request.app.state.es
        origin = get_feature(client, feature_id)
        return similar_places(client, settings.index, origin, lang)

    @app.get("/api/features/{feature_id}/vector-similar")
    def vector_similar(request: Request, feature_id: str,
                       lang: SimilarLanguage = Query("zh"),
                       min_similarity: float = Query(0.60, ge=0, le=1)):
        client = request.app.state.es
        origin = get_feature(client, feature_id, include_vectors=True)
        try:
            return vector_similar_places(client, settings.index, origin, lang, min_similarity,
                request.app.state.query_embeddings.embed)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(503, "向量搜索暂不可用，请检查模型服务后重试。") from exc

    return app


app = create_app()
