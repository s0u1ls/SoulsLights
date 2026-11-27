// Optional zero-cost Cloudflare Worker API for GitHub Pages (bind a KV namespace named SOULSLIGHTS_KV)
const ADMIN_USER = "admin";
const ADMIN_PASS = "ishaantuff";

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        },
      });
    }
    const url = new URL(request.url);
    const kv = env.SOULSLIGHTS_KV;
    const now = new Date().toISOString().replace("T", " ").slice(0, 19);
    const ip = request.headers.get("CF-Connecting-IP") || "";
    const ua = (request.headers.get("User-Agent") || "").slice(0, 200);

    if (url.pathname === "/api/track/visit" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      const visits = JSON.parse((await kv.get("visits")) || "[]");
      visits.unshift({ ip, user_agent: ua, page: body.page || "/", referrer: body.referrer || "", ts: now });
      await kv.put("visits", JSON.stringify(visits.slice(0, 200)));
      const total = Number((await kv.get("total_visits")) || "0") + 1;
      await kv.put("total_visits", String(total));
      return json({ ok: true });
    }

    if (url.pathname === "/api/track/download" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      const os = String(body.os || "").toLowerCase().includes("mac") ? "macos" : "windows";
      const dls = JSON.parse((await kv.get("downloads")) || "[]");
      dls.unshift({ os, ip, user_agent: ua, ts: now });
      await kv.put("downloads", JSON.stringify(dls.slice(0, 200)));
      const k = os === "macos" ? "mac_downloads" : "win_downloads";
      await kv.put(k, String(Number((await kv.get(k)) || "0") + 1));
      return json({ ok: true });
    }

    if (url.pathname === "/api/activate" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      const tok = String(body.token || "").trim().toUpperCase();
      const mid = String(body.machine_id || "").trim();
      const tokens = JSON.parse((await kv.get("tokens")) || "{}");
      const rec = tokens[tok];
      if (!rec) return json({ ok: false, error: "Invalid activation token." }, 403);
      if (rec.revoked) return json({ ok: false, error: "Token revoked." }, 403);
      if (!rec.is_master && rec.used && rec.used_by_machine && mid && rec.used_by_machine !== mid) {
        return json({ ok: false, error: "Token already used on another device." }, 403);
      }
      rec.used = 1; rec.uses = (rec.uses || 0) + 1; rec.used_by_machine = mid; rec.used_at = now;
      tokens[tok] = rec;
      await kv.put("tokens", JSON.stringify(tokens));
      return json({ ok: true, is_master: !!rec.is_master, message: "Token verified!" });
    }

    if (url.pathname === "/api/admin/login" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      if (body.username === ADMIN_USER && body.password === ADMIN_PASS) {
        return json({ ok: true, token: btoa(`${ADMIN_USER}:${ADMIN_PASS}`) });
      }
      return json({ ok: false, error: "Invalid admin credentials" }, 401);
    }

    const auth = (request.headers.get("Authorization") || "").replace("Bearer ", "");
    if (auth !== btoa(`${ADMIN_USER}:${ADMIN_PASS}`)) return json({ ok: false, error: "Unauthorized" }, 401);

    if (url.pathname === "/api/admin/stats") {
      const tokensObj = JSON.parse((await kv.get("tokens")) || "{}");
      const tokens = Object.entries(tokensObj).map(([token, v]) => ({ token, ...v }));
      const visits = JSON.parse((await kv.get("visits")) || "[]");
      const downloads = JSON.parse((await kv.get("downloads")) || "[]");
      const total_visits = Number((await kv.get("total_visits")) || String(visits.length));
      const win_downloads = Number((await kv.get("win_downloads")) || "0");
      const mac_downloads = Number((await kv.get("mac_downloads")) || "0");
      return json({
        ok: true,
        summary: {
          total_visits,
          unique_visitors: new Set(visits.map((v) => v.ip)).size,
          win_downloads,
          mac_downloads,
          total_downloads: win_downloads + mac_downloads,
          tokens_total: tokens.length,
          tokens_used: tokens.filter((t) => t.used && !t.is_master).length,
          tokens_unused: tokens.filter((t) => !t.used && !t.revoked && !t.is_master).length,
          tokens_revoked: tokens.filter((t) => t.revoked).length,
        },
        tokens, visits, downloads,
      });
    }

    if (url.pathname === "/api/admin/tokens" && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      const act = String(body.action || "");
      const tok = String(body.token || "").trim().toUpperCase();
      const tokens = JSON.parse((await kv.get("tokens")) || "{}");
      if (act === "generate") {
        const count = Math.max(1, Math.min(100, Number(body.count || 10)));
        const alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ", digits = "23456789", both = alpha + digits;
        const created = [];
        for (let i = 0; i < count * 4 && created.length < count; i++) {
          const arr = [];
          for (let j = 0; j < 3; j++) arr.push(digits[Math.floor(Math.random() * digits.length)]);
          for (let j = 0; j < 3; j++) arr.push(alpha[Math.floor(Math.random() * alpha.length)]);
          for (let j = 0; j < 4; j++) arr.push(both[Math.floor(Math.random() * both.length)]);
          arr.sort(() => Math.random() - 0.5);
          const nt = arr.join("");
          if (!tokens[nt]) {
            tokens[nt] = { is_master: 0, used: 0, revoked: 0, uses: 0, used_by_machine: "", used_at: "", created_at: now };
            created.push(nt);
          }
        }
        await kv.put("tokens", JSON.stringify(tokens));
        return json({ ok: true, created });
      }
      if (act === "revoke" && tok && tokens[tok] && !tokens[tok].is_master) tokens[tok].revoked = 1;
      if (act === "unrevoke" && tok && tokens[tok]) tokens[tok].revoked = 0;
      if (act === "reset" && tok && tokens[tok]) {
        tokens[tok].used = 0; tokens[tok].used_by_machine = ""; tokens[tok].used_at = "";
      }
      if (act === "clear_logs") {
        await kv.put("visits", "[]"); await kv.put("downloads", "[]");
        await kv.put("total_visits", "0"); await kv.put("win_downloads", "0"); await kv.put("mac_downloads", "0");
      }
      await kv.put("tokens", JSON.stringify(tokens));
      return json({ ok: true });
    }

    return json({ ok: false, error: "Not found" }, 404);
  },
};
