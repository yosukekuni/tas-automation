<?php
/**
 * ページ別JavaScript/JSON-LD配信（WAFバイパス用）
 * deploy_seo_moat.pyで分離されたscriptタグをwp_footer経由で出力
 * 生成日時: 2026-03-18 12:30
 */

add_action('wp_footer', function() {
    global $post;
    if (!$post) return;
    $slug = $post->post_name;
    if ($slug === 'drone-survey-market-report') {
        echo '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>';
    }
    if ($slug === 'drone-survey-market-report') {
        echo '<script>
document.addEventListener(\'DOMContentLoaded\', function() {
    var ctx = document.getElementById(\'monthlyChart\');
    if (ctx) {
        new Chart(ctx, {
            type: \'bar\',
            data: {
                labels: ["23-08", "23-09", "23-11", "24-03", "24-04", "24-05", "24-07", "24-12", "25-01", "25-03", "25-05", "26-02"],
                datasets: [{
                    label: \'受注件数\',
                    data: [8, 5, 2, 2, 1, 3, 1, 1, 2, 1, 1, 2],
                    backgroundColor: \'rgba(26, 86, 219, 0.7)\',
                    yAxisID: \'y\'
                }, {
                    label: \'受注額(万円)\',
                    data: [200, 33, 40, 12, 2, 67, 7, 8, 18, 7, 15, 59],
                    type: \'line\',
                    borderColor: \'#e63946\',
                    backgroundColor: \'transparent\',
                    yAxisID: \'y1\'
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: { position: \'left\', title: { display: true, text: \'件数\' } },
                    y1: { position: \'right\', title: { display: true, text: \'万円\' }, grid: { drawOnChartArea: false } }
                }
            }
        });
    }
});
</script>';
    }
});