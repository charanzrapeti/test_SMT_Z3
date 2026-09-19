#!/bin/bash

LOCAL="/mnt/d/masters/project_work/test_code"
REMOTE="g780658@omni.zimt.uni-siegen.de"
KEY="$HOME/.ssh/charan_windows_key"

echo "=============================="
echo "        OMNI MENU"
echo "=============================="
echo "1) Sync Local → OMNI"
echo "2) Sync OMNI → Local"
echo "3) Login to OMNI"
echo "4) Exit"
echo "=============================="

read -p "Select an option: " choice

case $choice in

    1)
        echo ""
        echo "Syncing Local → OMNI..."
        rsync -avz \
            -e "ssh -i $KEY" \
            "$LOCAL/" \
            "$REMOTE:~/test_code/"
        echo ""
        echo "Done."
        ;;

    2)
        echo ""
        echo "Syncing OMNI → Local..."
        rsync -avz \
            -e "ssh -i $KEY" \
            "$REMOTE:~/test_code/" \
            "$LOCAL/"
        echo ""
        echo "Done."
        ;;

    3)
        echo ""
        echo "Connecting to OMNI..."
        ssh -i "$KEY" "$REMOTE"
        ;;

    4)
        echo "Exiting."
        exit 0
        ;;

    *)
        echo "Invalid option."
        exit 1
        ;;
esac