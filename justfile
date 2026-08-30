export path="assets":
    python3 export.py "{{path}}"

force path="assets":
    python3 export.py "{{path}}" --force

clean-backups path="assets":
    find "{{path}}" -name "*.blend[0-9]*" -delete

clean path="assets":
    find "{{path}}" -name "*.blend[0-9]*" -delete
    find "{{path}}" -name "*.json" -delete
    find "{{path}}" -name "*.png" -delete
