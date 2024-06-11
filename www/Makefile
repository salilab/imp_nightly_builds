SUBDIRS=nonimp github-hook github-tutorial-doc
.PHONY: install ${SUBDIRS}
WEB=/guitar3/home/www/IMP
FILES=${WEB}/index.py ${WEB}/sorttable.js ${WEB}/testfunc.js ${WEB}/tests.css \
      ${WEB}/jquery-1.8.1.min.js ${WEB}/jquery.jqplot.min.js \
      ${WEB}/jqplot.dateAxisRenderer.min.js \
      ${WEB}/jqplot.canvasAxisLabelRenderer.min.js \
      ${WEB}/jqplot.canvasTextRenderer.min.js \
      ${WEB}/jqplot.cursor.min.js ${WEB}/jqplot.highlighter.min.js \
      ${WEB}/jquery.jqplot.css ${WEB}/excanvas.min.js

install: ${FILES} ${WEB}/README ${SUBDIRS}

${SUBDIRS}:
	${MAKE} -C $@

${WEB}/README: Makefile
	echo "Do not edit files in this directory!" > $@
	echo "Edit the originals (in the git repo)" >> $@
	echo "and use 'make' to install them here" >> $@
	chmod go-rwx $@

${WEB}/%: %
	cp -f $< $@
	chmod a-w $@
	chmod a+rx $@
