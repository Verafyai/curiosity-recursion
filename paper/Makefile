# make        builds main.pdf and whitepaper/whitepaper.pdf
# make tables regenerates results-values.tex and generated/*.tex from benchmark results (no hand-typed numbers)
H1 ?= ../results/v0/results.json
CORPUS ?= ../benchmark/results/v1/20261126T1600/results.json
# v0.2 result set (empty until the v0.2 bench has run); make tables V02=../benchmark/results/v1/<stamp>
V02 ?=
all: main.pdf whitepaper/whitepaper.pdf
tables:
	cd .. && .venv/bin/python eval/fill_v0.py --h1 $(patsubst ../%,%,$(H1)) --corpus $(patsubst ../%,%,$(CORPUS)) --audit $(patsubst ../%,%,$(dir $(CORPUS)))audit.json --out paper/
	if [ -n "$(V02)" ]; then cd .. && .venv/bin/python eval/fill_v02.py --run $(patsubst ../%,%,$(V02)) --out paper/ && .venv/bin/python eval/plots.py recall-vs-calls $(patsubst ../%,%,$(V02)) --out paper/figures/recall-vs-calls.pdf; fi
main.pdf: main.tex macros.tex refs.bib $(wildcard sections/*.tex) $(wildcard generated/*.tex) $(wildcard results-values.tex) $(wildcard results-values-v02.tex)
	pdflatex -interaction=nonstopmode -halt-on-error main.tex > /dev/null
	bibtex main > /dev/null || true
	pdflatex -interaction=nonstopmode -halt-on-error main.tex > /dev/null
	pdflatex -interaction=nonstopmode -halt-on-error main.tex | grep -E "Warning: (Reference|Citation)|Output written" || true
whitepaper/whitepaper.pdf: whitepaper/whitepaper.tex $(wildcard results-values.tex)
	cd whitepaper && pdflatex -interaction=nonstopmode -halt-on-error whitepaper.tex > /dev/null && pdflatex -interaction=nonstopmode -halt-on-error whitepaper.tex | grep "Output written" || true
clean:
	rm -f *.aux *.log *.out *.bbl *.blg *.toc whitepaper/*.aux whitepaper/*.log whitepaper/*.out
.PHONY: all tables clean
