<?php
/**
 * TAS Lark Lead Proxy - Updated for Contact Form
 * WordPress Code Snippets #54 (tas_lark_lead_proxy)
 * 
 * NOTE: このコードをWordPress管理画面 > Code Snippets > #54 に貼り付けてください
 * WAFの制限でAPIからの更新ができないため手動更新が必要です
 */

add_action('wp_ajax_tas_lark_lead', 'tas_lark_lead_fn');
add_action('wp_ajax_nopriv_tas_lark_lead', 'tas_lark_lead_fn');

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
    
    // Get Lark token
    $aid = 'cli_a92d697b1df89e1b';
    $asc = 'd6ZNyoAJbXN679ybZhC9vhCNxV4IcJFo';
    
    $tr = wp_remote_post('https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal', array(
        'headers' => array('Content-Type' => 'application/json'),
        'body' => json_encode(array('app_id' => $aid, 'app_secret' => $asc)),
        'timeout' => 10
    ));
    
    if (is_wp_error($tr)) {
        // Fallback: email notification
        tas_lead_email_fallback($co, $em, $mm, $channel);
        wp_send_json(array('ok' => true));
        wp_die();
    }
    
    $td = json_decode(wp_remote_retrieve_body($tr), true);
    $tk = isset($td['tenant_access_token']) ? $td['tenant_access_token'] : '';
    if (!$tk) {
        tas_lead_email_fallback($co, $em, $mm, $channel);
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
    
    if (!$lark_ok) {
        tas_lead_email_fallback($co, $em, $mm, $channel);
    }
    
    // Always notify CEO for contact form submissions
    if ($channel === '問い合わせフォーム') {
        wp_mail(
            'yosuke.toyoda@gmail.com',
            '【TAS】新規お問い合わせ: ' . ($co ?: '不明') . ' ' . ($name_val ?: '') . '様',
            "会社: {$co}\n氏名: {$name_val}\nメール: {$em}\n電話: {$phone_val}\n\n{$mm}",
            array('Content-Type: text/plain; charset=UTF-8')
        );
    }
    
    wp_send_json(array('ok' => $lark_ok || true));
    wp_die();
}

function tas_lead_email_fallback($co, $em, $mm, $channel) {
    wp_mail(
        'yosuke.toyoda@gmail.com',
        '【TAS・要手動登録】リード: ' . ($co ?: '不明'),
        "【Lark登録失敗 - 手動でCRMに登録してください】\n\nチャネル: {$channel}\n会社: {$co}\nメール: {$em}\n\n{$mm}",
        array('Content-Type: text/plain; charset=UTF-8')
    );
}
