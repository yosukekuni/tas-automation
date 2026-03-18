/**
 * Cloudflare Worker: PDF Lead Capture
 *
 * 土量計算ツール / 属人化リスク診断の結果PDF生成＆リード獲得
 *
 * Endpoints:
 *   POST /api/lead-capture
 *     Body: { email, tool_type, result_data }
 *     → メール検証 → CRMリード登録 → PDFダウンロードURL返却
 *
 *   GET /api/download-count
 *     → 公開用DL累計カウント
 *
 * KV Namespace: PDF_LEADS (DLカウント・リード一時保存)
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);

    if (url.pathname === '/api/lead-capture' && request.method === 'POST') {
      return handleLeadCapture(request, env);
    }

    if (url.pathname === '/api/download-count') {
      return handleDownloadCount(env);
    }

    return new Response('Not Found', { status: 404 });
  },
};

async function handleLeadCapture(request, env) {
  try {
    const body = await request.json();
    const { email, tool_type, result_data } = body;

    // バリデーション
    if (!email || !isValidEmail(email)) {
      return jsonResponse({ error: 'メールアドレスが無効です' }, 400);
    }

    if (!['earthwork_calc', 'risk_assessment'].includes(tool_type)) {
      return jsonResponse({ error: '不明なツール種別です' }, 400);
    }

    // DLカウント更新 (KV)
    const countKey = `dl_count_${tool_type}`;
    const totalKey = 'dl_count_total';

    const currentCount = parseInt(await env.PDF_LEADS.get(countKey) || '0');
    const currentTotal = parseInt(await env.PDF_LEADS.get(totalKey) || '0');

    await env.PDF_LEADS.put(countKey, String(currentCount + 1));
    await env.PDF_LEADS.put(totalKey, String(currentTotal + 1));

    // リード情報を一時保存（バッチでCRM同期）
    const leadKey = `lead_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    await env.PDF_LEADS.put(leadKey, JSON.stringify({
      email,
      tool_type,
      timestamp: new Date().toISOString(),
      result_summary: summarizeResult(result_data, tool_type),
    }), { expirationTtl: 86400 * 30 }); // 30日保持

    return jsonResponse({
      success: true,
      message: 'リード登録完了。PDFのダウンロードを開始します。',
      download_count: currentTotal + 1,
    });

  } catch (e) {
    return jsonResponse({ error: '処理に失敗しました' }, 500);
  }
}

async function handleDownloadCount(env) {
  const total = parseInt(await env.PDF_LEADS.get('dl_count_total') || '0');

  // 公開用丸め（社会的証明）
  let display;
  if (total < 100) {
    display = `${total}件`;
  } else if (total < 1000) {
    display = `${Math.floor(total / 100) * 100}件以上`;
  } else {
    display = `${Math.floor(total / 1000).toLocaleString()},000件以上`;
  }

  return jsonResponse({
    total,
    display,
    updated_at: new Date().toISOString(),
  });
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function summarizeResult(data, toolType) {
  if (!data) return '';
  if (toolType === 'earthwork_calc') {
    return `面積:${data.area || '?'}m2, 土量:${data.volume || '?'}m3`;
  }
  if (toolType === 'risk_assessment') {
    return `スコア:${data.score || '?'}/100`;
  }
  return '';
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...CORS_HEADERS,
    },
  });
}
