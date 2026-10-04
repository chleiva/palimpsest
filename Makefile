.PHONY: test tables figures paper setting1 data clean
test:            ; python -m pytest tests -q
tables:          ; python scripts/make_tables.py
figures:         ; python scripts/make_figures.py
paper: tables figures
	cd paper && pdflatex -interaction=nonstopmode main >/dev/null && bibtex main >/dev/null && pdflatex -interaction=nonstopmode main >/dev/null && pdflatex -interaction=nonstopmode main >/dev/null && echo "paper/main.pdf"
setting1:
	python scripts/generate_streams.py 500 data/setting1 && python scripts/run_setting1.py data/setting1 --out data/setting1_results.json
data:            ; python scripts/fetch_release_data.py
clean:           ; rm -f paper/*.aux paper/*.bbl paper/*.blg paper/*.log paper/*.out
