#![cfg(not(feature = "enterprise"))]

use serde_json::json;
use sqlx::{Pool, Postgres};
use windmill_test_utils::*;

#[sqlx::test(fixtures("base"))]
async fn workspace_lifecycle_has_no_community_count_cap(db: Pool<Postgres>) -> anyhow::Result<()> {
    initialize_tracing().await;
    let server = ApiServer::start(db.clone()).await?;
    let base = format!("http://localhost:{}/api", server.addr.port());
    let client = reqwest::Client::new();

    for id in ["count-a", "count-b", "count-c", "count-d"] {
        let response = client
            .post(format!("{base}/workspaces/create"))
            .bearer_auth("SECRET_TOKEN")
            .json(&json!({ "id": id, "name": id }))
            .send()
            .await?;
        assert_eq!(response.status(), 200, "{}", response.text().await?);
    }

    for id in ["count-a", "count-b"] {
        let response = client
            .post(format!("{base}/w/{id}/workspaces/archive"))
            .bearer_auth("SECRET_TOKEN")
            .send()
            .await?;
        assert_eq!(response.status(), 200, "{}", response.text().await?);
    }
    let archived: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM workspace WHERE id IN ('count-a', 'count-b') AND deleted = true",
    )
    .fetch_one(&db)
    .await?;
    assert_eq!(archived, 2);

    let response = client
        .post(format!("{base}/workspaces/unarchive/count-a"))
        .bearer_auth("SECRET_TOKEN")
        .send()
        .await?;
    assert_eq!(response.status(), 200, "{}", response.text().await?);

    let active: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM workspace WHERE id IN ('count-a', 'count-c', 'count-d') AND deleted = false",
    )
    .fetch_one(&db)
    .await?;
    assert_eq!(active, 3);
    Ok(())
}
