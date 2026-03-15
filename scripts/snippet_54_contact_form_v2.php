<?php
/**
 * TAS Lark Lead Proxy - v2: Spam Filter + Multi-Channel Notification
 * WordPress Code Snippets #54 (tas_lark_lead_proxy)
 *
 * v2 Changes:
 * - スパムフィルタ追加（フリーメール + 営業キーワード = スパム判定）
 * - Lark Bot DM即時通知（CEO + 営業）
 * - 土量計算機リードにも全チャネル通知
 *
 * NOTE: このコードをWordPress管理画面 > Code Snippets > #54 に貼り付けてください
 * WAFの制限でAPIからの更新ができないため手動更新が必要です
 */

add_action('wp_ajax_tas_lark_lead', 'tas_lark_lead_fn');
add_action('wp_ajax_nopriv_tas_lark_lead', 'tas_lark_lead_fn');

/**
 * スパム判定: フリーメール + 営業キーワード
 * 法人メールはスパム判定しない（見込み客の可能性）
 */
function tas_is_spam_lead($email, $company, $message) {
    $spam_domains = array(
        'gmail.com', 'yahoo.co.jp', 'yahoo.com', 'hotmail.com', 'outlook.com',
        'outlook.jp', 'icloud.com', 'me.com', 'aol.com', 'live.jp', 'live.com',
        'msn.com', 'nifty.com', 'biglobe.ne.jp', 'excite.co.jp'
    );
    $spam_keywords = array(
        '営業', '提案', 'ご案内', 'セミナー', '無料', 'キャンペーン',
        '人材', '採用', 'SEO', 'ホームページ', 'web制作', 'Web制作', '広告',
        '保険', '不動産投資', 'コンサル', '業務効率', '助成金', '補助金',
        'リスティング', 'マーケティング', '集客', 'DX支援', '業務改善',
        'ウェブ制作', 'LP制作', 'SNS運用', '動画制作', 'コスト削減'
    );

    $email_parts = explode('@', $email);
    $email_domain = isset($email_parts[1]) ? $email_parts[1] : '';
    $is_free_email = in_array(strtolower($email_domain), $spam_domains);

    if (!$is_free_email) {
        return false; // 法人メールはスパム判定しない
    }

    $check_text = mb_strtolower($company . ' ' . $message);
    foreach ($spam_keywords as $kw) {
        if (mb_strpos($check_text, mb_strtolower($kw)) !== false) {
            return true;
        }
    }

    return false;
}

function tas_lark_lead_fn() {
    $em = filter_input(INPUT_POST, 'email', FILTER_SANITIZE_EMAIL);
    $co = filter_input(INPUT_POST, 'company', FILTER_SANITIZE_FULL_SPECIAL_CHARS);
    $mm = filter_input(INPUT_POST, 'memo', FILTER_SANITIZE_FULL_SPECIAL_CHARS);
    $src = filter_input(INPUT_POST, 'source', FILTER_SANITIZE_FULL_SPECIAL_CHARS);

    if (!$em) {
        wp_send_json(array('ok' => false));
        wp_die();
    }

    // Parse structured memo for individual fields
    $name_val = '';
    $phone_val = '';
    $title_val = '';
    $services = array();
    $schedule_val = '';
    $site_val = '';
    $message_val = '';
    $channel = '土量計算機'; // default

    if (strpos($mm, '[問い合わせフォーム]') !== false) {
        $channel = '問い合わせフォーム';
        $lines = explode("\n", $mm);
        foreach ($lines as $line) {
            $line = trim($line);
            if (strpos($line, '氏名: ') === 0) $name_val = substr($line, strlen('氏名: '));
            elseif (strpos($line, '電話: ') === 0) $phone_val = substr($line, strlen('電話: '));
            elseif (strpos($line, '役職: ') === 0) $title_val = substr($line, strlen('役職: '));
            elseif (strpos($line, '依頼内容: ') === 0) $services = array_map('trim', explode(', ', substr($line, strlen('依頼内容: '))));
            elseif (strpos($line, 'スケジュール: ') === 0) $schedule_val = substr($line, strlen('スケジュール: '));
            elseif (strpos($line, '現場: ') === 0) $site_val = substr($line, strlen('現場: '));
            elseif (strpos($line, '内容: ') === 0) $message_val = substr($line, strlen('内容: '));
        }
    }
    if ($src === 'contact') $channel = '問い合わせフォーム';

    // スパム判定
    $is_spam = tas_is_spam_lead($em, $co, $message_val . ' ' . $mm);

    // Get Lark token
    $aid = 'cli_a92d697b1df89e1b';
    $asc = 'd6ZNyoAJbXN679ybZhC9vhCNxV4IcJFo';

    $tr = wp_remote_post('https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal', array(
        'headers' => array('Content-Type' => 'application/json'),
        'body' => json_encode(array('app_id' => $aid, 'app_secret' => $asc)),
        'timeout' => 10
    ));

    if (is_wp_error($tr)) {
        if (!$is_spam) {
            tas_lead_email_fallback($co, $em, $mm, $channel);
        }
        wp_send_json(array('ok' => true));
        wp_die();
    }

    $td = json_decode(wp_remote_retrieve_body($tr), true);
    $tk = isset($td['tenant_access_token']) ? $td['tenant_access_token'] : '';
    if (!$tk) {
        if (!$is_spam) {
            tas_lead_email_fallback($co, $em, $mm, $channel);
        }
        wp_send_json(array('ok' => true));
        wp_die();
    }

    // Build record fields
    $bt = 'BodWbgw6DaHP8FspBTYjT8qSpOe';
    $ti = 'tblN53hFIQoo4W8j';
    $rurl = 'https://open.larksuite.com/open-apis/bitable/v1/apps/' . $bt . '/tables/' . $ti . '/records';

    $flds = array();
    $flds['メールアドレス'] = $em;
    $flds['接触チャネル'] = $channel;
    if ($co) $flds['会社名'] = $co;
    if ($name_val) $flds['氏名'] = $name_val;
    if ($phone_val) $flds['電話番号'] = $phone_val;
    if ($title_val) $flds['役職'] = $title_val;
    if (!empty($services)) $flds['案件タイプ'] = $services;
    if ($schedule_val) $flds['想定スケジュール'] = $schedule_val;
    if ($site_val) $flds['現場名'] = $site_val;
    if ($message_val) $flds['お問い合わせ内容（自由記述）'] = $message_val;
    $flds['営業フェーズ'] = '未接触';
    // memo always stored as backup
    if ($mm) $flds['備考・メモ'] = $mm;

    // スパムの場合はタグ付与
    if ($is_spam) {
        $flds['営業フェーズ'] = 'スパム';
        $flds['備考・メモ'] = '[SPAM判定] ' . ($mm ?: '');
    }

    $rr = wp_remote_post($rurl, array(
        'headers' => array(
            'Content-Type' => 'application/json',
            'Authorization' => 'Bearer ' . $tk
        ),
        'body' => json_encode(array('fields' => $flds)),
        'timeout' => 10
    ));

    $lark_ok = false;
    if (!is_wp_error($rr)) {
        $rd = json_decode(wp_remote_retrieve_body($rr), true);
        $lark_ok = isset($rd['data']['record']);
    }

    if (!$lark_ok && !$is_spam) {
        tas_lead_email_fallback($co, $em, $mm, $channel);
    }

    // 通知（スパムでない場合のみ）
    if (!$is_spam) {
        $lead_summary = "会社: {$co}\n氏名: {$name_val}\nメール: {$em}\n電話: {$phone_val}\nチャネル: {$channel}";
        if ($message_val) $lead_summary .= "\n内容: " . mb_substr($message_val, 0, 200);
        if (!empty($services)) $lead_summary .= "\n依頼内容: " . implode(', ', $services);

        $subject_label = ($channel === '問い合わせフォーム') ? '新規お問い合わせ' : '土量計算機リード';
        $email_subject = '【TAS】' . $subject_label . ': ' . ($co ?: '不明') . ' ' . ($name_val ?: '') . '様';

        // 1. CEO メール通知
        wp_mail(
            'yosuke.toyoda@gmail.com',
            $email_subject,
            $lead_summary,
            array('Content-Type: text/plain; charset=UTF-8')
        );

        // 2. CEO Lark Bot DM
        tas_send_lark_bot_dm($tk, 'ou_d2e2e520a442224ea9d987c6186341ce', $email_subject . "\n\n" . $lead_summary);

        // 3. 営業チーム通知（両名に送信）
        // 新美: Lark Bot DM
        tas_send_lark_bot_dm($tk, 'ou_189dc637b61a83b886d356becb3ae18e', $email_subject . "\n\n" . $lead_summary);
        // 政木: メール（Lark DM不可、外部委託）
        wp_mail(
            'y-masaki@riseasone.jp',
            $email_subject,
            $lead_summary,
            array('Content-Type: text/plain; charset=UTF-8')
        );
    }

    wp_send_json(array('ok' => $lark_ok || true));
    wp_die();
}

/**
 * Lark Bot DM送信
 */
function tas_send_lark_bot_dm($token, $open_id, $message) {
    $url = 'https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id';
    $body = array(
        'receive_id' => $open_id,
        'msg_type' => 'text',
        'content' => json_encode(array('text' => $message))
    );

    $response = wp_remote_post($url, array(
        'headers' => array(
            'Content-Type' => 'application/json',
            'Authorization' => 'Bearer ' . $token
        ),
        'body' => json_encode($body),
        'timeout' => 10
    ));

    if (is_wp_error($response)) {
        error_log('TAS Lark Bot DM failed: ' . $response->get_error_message());
        return false;
    }
    return true;
}

function tas_lead_email_fallback($co, $em, $mm, $channel) {
    wp_mail(
        'yosuke.toyoda@gmail.com',
        '【TAS・要手動登録】リード: ' . ($co ?: '不明'),
        "【Lark登録失敗 - 手動でCRMに登録してください】\n\nチャネル: {$channel}\n会社: {$co}\nメール: {$em}\n\n{$mm}",
        array('Content-Type: text/plain; charset=UTF-8')
    );
}
