# Makefile.include should set the WEBTOP variable to the location to install to
include Makefile.include

.PHONY: test install

test:
	py.test --pep8

install::
	mkdir -p ${WEBTOP}/results/templates
	mkdir -p ${WEBTOP}/static/images
	cp results/*.py ${WEBTOP}/results/
	cp results/templates/*.html ${WEBTOP}/results/templates/
	cp static/*.{css,js} ${WEBTOP}/static/
	echo "import sys; sys.path.insert(0, '${WEBTOP}')" > ${WEBTOP}/results.wsgi
	echo "from results import app as application" >> ${WEBTOP}/results.wsgi
	@echo "Do not edit files in this directory!" > ${WEBTOP}/README
	@echo "Edit the originals and use 'make' to install them here" >> ${WEBTOP}/README
