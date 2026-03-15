#!/bin/bash
# NAS自動マウントスクリプト
# 自宅LAN: 直接IP接続 / 外出先: QuickConnect経由（SMBは不可、smbclient使用）

NAS_IP="192.168.0.34"
CREDS="/etc/nas-credentials"
SHARES=("0_inbox:nas" "1_projects:nas1" "2_area:nas2" "3_resources:nas3" "4_archive:nas4")

# NASが自宅LANにあるか確認
if ping -c 1 -W 2 "$NAS_IP" > /dev/null 2>&1; then
    echo "[NAS] 自宅LAN接続確認: $NAS_IP"
    for share_mount in "${SHARES[@]}"; do
        share="${share_mount%%:*}"
        mount="/mnt/${share_mount##*:}"
        if mountpoint -q "$mount" 2>/dev/null; then
            echo "  [OK] $mount already mounted"
        else
            sudo mount -t cifs "//$NAS_IP/$share" "$mount" \
                -o credentials=$CREDS,vers=3.0,iocharset=utf8,nofail 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "  [OK] $mount mounted"
            else
                echo "  [NG] $mount mount failed"
            fi
        fi
    done
else
    echo "[NAS] 自宅LANに接続されていません"
    echo "  QuickConnect: http://QuickConnect.to/yousuketoyoda"
    echo "  smbclientで直接アクセス:"
    echo "    smbclient //192.168.0.34/2_area -U yosuke.toyoda%qZhjsUs3"
    echo ""
    echo "  ※外出先からはDSM Web UIまたはSynology Driveアプリを使用してください"
fi
