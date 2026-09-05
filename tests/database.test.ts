import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";

test("migration enforces owner-only reads, denies client writes and supports CAS", async () => {
  const db = new PGlite();
  try {
    await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
      create schema auth; create table auth.users (id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
      grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
    await db.exec(
      await readFile("supabase/migrations/202609050001_attempts.sql", "utf8"),
    );
    const owner = "11111111-1111-4111-8111-111111111111";
    const other = "22222222-2222-4222-8222-222222222222";
    const id = "33333333-3333-4333-8333-333333333333";
    const editor = "44444444-4444-4444-8444-444444444444";
    await db.query("insert into auth.users values ($1), ($2)", [owner, other]);
    const payload = {
      id,
      ownerId: owner,
      bankVersion: "v1",
      editorId: editor,
      revision: 0,
    };
    await db.query(
      "insert into public.attempts (id,owner_id,bank_version,editor_id,payload) values ($1,$2,$3,$4,$5)",
      [id, owner, "v1", editor, payload],
    );
    await db.exec(
      `set role authenticated; set request.jwt.claim.sub = '${other}';`,
    );
    assert.equal(
      (await db.query("select * from public.attempts")).rows.length,
      0,
    );
    await db.exec(`set request.jwt.claim.sub = '${owner}';`);
    assert.equal(
      (await db.query("select * from public.attempts")).rows.length,
      1,
    );
    await assert.rejects(
      db.exec("update public.attempts set revision=5"),
      /permission denied/,
    );
    await assert.rejects(
      db.exec("delete from public.attempts"),
      /permission denied/,
    );
    await db.exec("set role anon;");
    await assert.rejects(
      db.exec("select * from public.attempts"),
      /permission denied/,
    );
    await db.exec("set role service_role;");
    const next = { ...payload, revision: 1 };
    const sql =
      "update public.attempts set revision=1,payload=$1 where id=$2 and owner_id=$3 and revision=0 and editor_id=$4 returning id";
    assert.equal(
      (await db.query(sql, [next, id, owner, editor])).rows.length,
      1,
    );
    assert.equal(
      (await db.query(sql, [next, id, owner, editor])).rows.length,
      0,
    );
    await assert.rejects(
      db.query("update public.attempts set payload=$1 where id=$2", [
        { ...next, ownerId: other },
        id,
      ]),
      /payload_owner_matches/,
    );
  } finally {
    await db.close();
  }
});
