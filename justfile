export path="assets":
    go run . export "{{path}}"

force path="assets":
    go run . export "{{path}}" --force

build:
    go build -o blexport .

clean-backups path="assets":
    find "{{path}}" -name "*.blend[0-9]*" -delete

clean path="assets":
    find "{{path}}" -name "*.blend[0-9]*" -delete
    find "{{path}}" -name "*.json" -delete
    find "{{path}}" -name "*.png" -delete
