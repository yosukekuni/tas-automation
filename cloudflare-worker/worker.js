/**
 * Cloudflare Worker: Lark Bot Event Receiver → GitHub Actions Dispatcher
 *
 * Lark Event Subscription (im.message.receive_v1) を受信し、
 * 送信者チェック後に GitHub repository_dispatch でワークフローをトリガー。
 * 即座に「受け付けました」とLark DMで返信。
 *
 * 環境変数 (Cloudflare Workers Secrets):
 *   LARK_APP_ID, LARK_APP_SECRET, LARK_VERIFICATION_TOKEN,
 *   LARK_ENCRYPT_KEY (optional), GITHUB_TOKEN, GITHUB_REPO, ALLOWED_OPEN_ID
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ── CORS preflight for contact form ──
    if (request.method === "OPTIONS" && url.pathname === "/tomoshi-contact") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "https://tomoshi.jp",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    // ── TOMOSHI Contact Form endpoint ──
    if (request.method === "POST" && url.pathname === "/tomoshi-contact") {
      return handleTomoshiContact(request, env);
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    // ── 1. Lark Event Subscription challenge 検証 ──
    if (body.type === "url_verification") {
      return new Response(
        JSON.stringify({ challenge: body.challenge }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // ── 2. Lark v2 event schema の challenge (encrypt なし) ──
    if (body.challenge) {
      return new Response(
        JSON.stringify({ challenge: body.challenge }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // ── 3. verification token チェック ──
    const token = body.header?.token || body.token;
    if (token && env.LARK_VERIFICATION_TOKEN && token !== env.LARK_VERIFICATION_TOKEN) {
      return new Response("Forbidden", { status: 403 });
    }

    // ── 4. イベントパース ──
    const eventType = body.header?.event_type || body.event?.type;
    if (eventType !== "im.message.receive_v1") {
      // 対象外のイベントは OK で返す（Lark がリトライしないように）
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    const event = body.event;
    const sender = event?.sender?.sender_id?.open_id;
    const message = event?.message;
    const messageType = message?.message_type;
    const chatType = message?.chat_type;
    const messageId = message?.message_id;

    // ── 5. 送信者チェック（セキュリティ） ──
    const allowedOpenId = env.ALLOWED_OPEN_ID || "ou_d2e2e520a442224ea9d987c6186341ce";
    if (sender !== allowedOpenId) {
      console.log(`Ignored: sender=${sender} is not allowed`);
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // ── 6. テキストメッセージのみ処理 ──
    if (messageType !== "text") {
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // メッセージ本文を取得
    let text = "";
    try {
      const content = JSON.parse(message.content);
      text = content.text || "";
    } catch {
      text = message.content || "";
    }

    if (!text.trim()) {
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // ── 7. Lark DMで「受け付けました」と即座に返信 ──
    const larkReplyPromise = replyToLark(env, sender, text, messageId);

    // ── 8. GitHub repository_dispatch を発火 ──
    const githubPromise = triggerGitHubDispatch(env, text, sender, messageId);

    // 並列実行して結果を待つ
    const [larkResult, githubResult] = await Promise.allSettled([
      larkReplyPromise,
      githubPromise,
    ]);

    if (githubResult.status === "rejected") {
      console.error("GitHub dispatch failed:", githubResult.reason);
    }
    if (larkResult.status === "rejected") {
      console.error("Lark reply failed:", larkResult.reason);
    }

    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  },
};


// ── TOMOSHI Contact Form Handler ──
async function handleTomoshiContact(request, env) {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "https://tomoshi.jp",
    "Content-Type": "application/json",
  };

  let formData;
  try {
    formData = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: corsHeaders,
    });
  }

  // Validate required fields
  const { company, name, email, phone, message, source } = formData;
  if (!name || !email || !message) {
    return new Response(
      JSON.stringify({ error: "name, email, message are required" }),
      { status: 400, headers: corsHeaders }
    );
  }

  // Simple spam check: honeypot field
  if (formData._hp) {
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: corsHeaders,
    });
  }

  try {
    const token = await getLarkToken(env);
    const baseToken = "UEHQbYevMaFvqIs60r3j92W6puu"; // TOMOSHI独立CRM Base
    const tableId = "tblAmZMD8DEWQGw0"; // TOMOSHI_リード

    // Create record in Lark Base
    const fields = {
      "会社名": company || "",
      "担当者名": name,
      "メール": email,
      "電話": phone || "",
      "メモ": message,
      "流入元": source || "Web検索",
      "ステータス": "新規",
      "初回接触日": Date.now(),
    };

    const resp = await fetch(
      `https://open.larksuite.com/open-apis/bitable/v1/apps/${baseToken}/tables/${tableId}/records`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ fields }),
      }
    );

    const result = await resp.json();
    if (result.code !== 0) {
      console.error("Lark Base create failed:", JSON.stringify(result));
      return new Response(
        JSON.stringify({ error: "Failed to save inquiry" }),
        { status: 500, headers: corsHeaders }
      );
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: corsHeaders,
    });
  } catch (err) {
    console.error("Contact form error:", err);
    return new Response(
      JSON.stringify({ error: "Internal server error" }),
      { status: 500, headers: corsHeaders }
    );
  }
}


// ── Lark tenant_access_token 取得 ──
async function getLarkToken(env) {
  const resp = await fetch(
    "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app_id: env.LARK_APP_ID,
        app_secret: env.LARK_APP_SECRET,
      }),
    }
  );
  const data = await resp.json();
  return data.tenant_access_token;
}


// ── Lark DM 返信 ──
async function replyToLark(env, openId, originalText, messageId) {
  const token = await getLarkToken(env);
  const ackText = `受け付けました: 「${originalText.substring(0, 50)}${originalText.length > 50 ? "..." : ""}」\n処理中です。完了後に結果を送信します。`;

  const resp = await fetch(
    "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        receive_id: openId,
        msg_type: "text",
        content: JSON.stringify({ text: ackText }),
      }),
    }
  );

  if (!resp.ok) {
    const errBody = await resp.text();
    throw new Error(`Lark reply failed: ${resp.status} ${errBody}`);
  }
}


// ── GitHub repository_dispatch ──
async function triggerGitHubDispatch(env, text, senderOpenId, messageId) {
  const repo = env.GITHUB_REPO || "yosukekuni/tas-automation";
  const url = `https://api.github.com/repos/${repo}/dispatches`;

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github.v3+json",
      "Content-Type": "application/json",
      "User-Agent": "TAS-Cloudflare-Worker",
    },
    body: JSON.stringify({
      event_type: "lark-command",
      client_payload: {
        message: text,
        sender_open_id: senderOpenId,
        message_id: messageId,
        timestamp: new Date().toISOString(),
      },
    }),
  });

  if (!resp.ok) {
    const errBody = await resp.text();
    throw new Error(`GitHub dispatch failed: ${resp.status} ${errBody}`);
  }
}
