# make        builds main.pdf and whitepaper/whitepaper.pdf
# make tables regenerates results-values.tex and generated/*.tex from benchmark results (no hand-typed numbers)
H1 ?= ../results/v0/results.json
CORPUS ?= $(lastword $(sort $(wildcard ../benchmark/results/*/*/results.json)))
all: main.pdf whitepaper/whitepaper.pdf
tables:
	cd .. && .venv/bin/python eval/fill_v0.py --h1 $(patsubst ../%,%,$(H1)) --corpus $(patsubst ../%,%,$(CORPUS)) --audit $(patsubst ../%,%,$(dir $(CORPUS)))audit.json --out paper/
main.pdf: main.tex macros.tex refs.bib $(wildcard sections/*.tex) $(wildcard generated/*.tex) $(wildcard results-values.tex)
	pdflatex -interaction=nonstopmode -halt-on-error main.tex > /dev/null
	bibtex main > /dev/null || true
	pdflatex -interaction=nonstopmode -halt-on-error main.tex > /dev/null
	pdflatex -interaction=nonstopmode -halt-on-error main.tex | grep -E "Warning: (Reference|Citation)|Output written" || true
whitepaper/whitepaper.pdf: whitepaper/whitepaper.tex $(wildcard results-values.tex)
	cd whitepaper && pdflatex -interaction=nonstopmode -halt-on-error whitepaper.tex > /dev/null && pdflatex -interaction=nonstopmode -halt-on-error whitepaper.tex | grep "Output written" || true
clean:
	rm -f *.aux *.log *.out *.bbl *.blg *.toc whitepaper/*.aux whitepaper/*.log whitepaper/*.out
.PHONY: all tables clean
