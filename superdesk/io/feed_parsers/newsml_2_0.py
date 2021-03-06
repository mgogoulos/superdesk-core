# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013 - 2018 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license


import arrow
import datetime
import logging

from superdesk.errors import ParserError
from superdesk.io.registry import register_feed_parser
from superdesk.io.feed_parsers import XMLFeedParser
from superdesk.io.iptc import subject_codes
from superdesk.metadata.item import ITEM_TYPE, CONTENT_TYPE
from superdesk.metadata.utils import is_normal_package

XMLNS = 'http://iptc.org/std/nar/2006-10-01/'
XHTML = 'http://www.w3.org/1999/xhtml'

logger = logging.getLogger(__name__)


class NewsMLTwoFeedParser(XMLFeedParser):
    """
    Feed Parser which can parse if the feed is in NewsML 2 format.
    """

    NAME = 'newsml2'

    label = 'News ML 2.0 Parser'

    def can_parse(self, xml):
        return xml.tag.endswith('newsMessage')

    def parse(self, xml, provider=None):
        self.root = xml
        items = []
        try:
            header = self.parse_header(xml)
            for item_set in xml.findall(self.qname('itemSet')):
                for item_tree in item_set:
                    item = self.parse_item(item_tree)
                    item['priority'] = header['priority']
                    items.append(item)
            return items
        except Exception as ex:
            raise ParserError.newsmlTwoParserError(ex, provider)

    def parse_item(self, tree):
        item = dict()
        item['guid'] = tree.attrib['guid'] + ':' + tree.attrib['version']
        item['uri'] = tree.attrib['guid']
        item['version'] = tree.attrib['version']

        self.parse_item_meta(tree, item)
        self.parse_content_meta(tree, item)
        self.parse_rights_info(tree, item)

        if is_normal_package(item):
            self.parse_group_set(tree, item)
        else:
            self.parse_content_set(tree, item)

        return item

    def parse_header(self, tree):
        """Parse header element.

        :param tree:
        :return: dict
        """
        header = tree.find(self.qname('header'))
        priority = 5
        if header is not None:
            priority = self.map_priority(header.find(self.qname('priority')).text)

        return {'priority': priority}

    def parse_item_meta(self, tree, item):
        """Parse itemMeta tag"""
        meta = tree.find(self.qname('itemMeta'))
        item[ITEM_TYPE] = meta.find(self.qname('itemClass')).attrib['qcode'].split(':')[1]
        item['versioncreated'] = self.datetime(meta.find(self.qname('versionCreated')).text)
        item['firstcreated'] = self.datetime(meta.find(self.qname('firstCreated')).text)
        item['pubstatus'] = (meta.find(self.qname('pubStatus')).attrib['qcode'].split(':')[1]).lower()
        item['ednote'] = meta.find(self.qname('edNote')).text if meta.find(self.qname('edNote')) is not None else ''

    def parse_content_meta(self, tree, item):
        """Parse contentMeta tag"""
        meta = tree.find(self.qname('contentMeta'))

        def parse_meta_item_text(key, dest=None, elemTree=None):
            if dest is None:
                dest = key

            if elemTree is None:
                elemTree = meta

            elem = elemTree.find(self.qname(key))
            if elem is not None:
                if dest == 'urgency':
                    item[dest] = int(elem.text)
                else:
                    item[dest] = elem.text

        parse_meta_item_text('urgency')
        parse_meta_item_text('slugline')
        parse_meta_item_text('headline')
        # parse_meta_item_text('creditline')
        parse_meta_item_text('by', 'byline')

        item['slugline'] = item.get('slugline', '')
        item['headline'] = item.get('headline', '')

        try:
            item['description_text'] = meta.find(self.qname('description')).text
            item['archive_description'] = item['description_text']
        except AttributeError:
            pass

        try:
            item['language'] = meta.find(self.qname('language')).get('tag')
        except AttributeError:
            pass

        self.parse_content_subject(meta, item)
        self.parse_content_place(meta, item)

        for info_source in meta.findall(self.qname('infoSource')):
            if info_source.get('role', '') == 'cRole:source':
                item['original_source'] = info_source.get('literal')
                break

        item['genre'] = []
        for genre_el in meta.findall(self.qname('genre')):
            for name_el in genre_el.findall(self.qname('name')):
                lang = name_el.get(self.qname("lang", ns='xml'))
                if lang and lang.startswith('en'):
                    item['genre'].append({'name': name_el.text})

    def parse_content_subject(self, tree, item):
        """Parse subj type subjects into subject list."""
        item['subject'] = []
        for subject in tree.findall(self.qname('subject')):
            qcode_parts = subject.get('qcode', '').split(':')
            if len(qcode_parts) == 2 and qcode_parts[0] == 'subj':
                try:
                    item['subject'].append({
                        'qcode': qcode_parts[1],
                        'name': subject_codes[qcode_parts[1]]
                    })
                except KeyError:
                    logger.debug("Subject code '%s' not found" % qcode_parts[1])

    def parse_content_place(self, tree, item):
        """Parse subject with type="cptType:5" into place list."""
        for subject in tree.findall(self.qname('subject')):
            if subject.get('type', '') == 'cptType:5':
                item['place'] = []
                item['place'].append({'name': self.get_literal_name(subject)})
                broader = subject.find(self.qname('broader'))
                if broader is not None:
                    item['place'].append({'name': self.get_literal_name(broader)})

    def parse_rights_info(self, tree, item):
        """Parse Rights Info tag"""
        info = tree.find(self.qname('rightsInfo'))
        if info is not None:
            item['usageterms'] = getattr(info.find(self.qname('usageTerms')), 'text', '')
            # item['copyrightholder'] = info.find(self.qname('copyrightHolder')).attrib['literal']
            # item['copyrightnotice'] = getattr(info.find(self.qname('copyrightNotice')), 'text', None)

    def parse_group_set(self, tree, item):
        item['groups'] = []
        for group in tree.find(self.qname('groupSet')):
            data = {}
            data['id'] = group.attrib['id']
            data['role'] = group.attrib['role']
            data['refs'] = self.parse_refs(group)
            item['groups'].append(data)

    def parse_refs(self, group_tree):
        refs = []
        for tree in group_tree:
            if 'idref' in tree.attrib:
                refs.append({'idRef': tree.attrib['idref']})
            else:
                ref = {}
                if 'version' in tree.attrib:
                    ref['residRef'] = tree.attrib['residref'] + ':' + tree.attrib['version']
                else:
                    ref['residRef'] = tree.attrib['residref']
                ref['contentType'] = tree.attrib['contenttype']
                ref['itemClass'] = tree.find(self.qname('itemClass')).attrib['qcode']

                for headline in tree.findall(self.qname('headline')):
                    ref['headline'] = headline.text

                refs.append(ref)
        return refs

    def parse_content_set(self, tree, item):
        item['renditions'] = {}
        for content in tree.find(self.qname('contentSet')):
            if content.tag == self.qname('inlineXML'):
                try:
                    item['word_count'] = int(content.attrib['wordcount'])
                except KeyError:
                    pass
                content = self.parse_inline_content(content)
                item['body_html'] = content.get('content')
                if 'format' in content:
                    item['format'] = content.get('format')
            elif content.tag == self.qname('inlineData'):
                item['body_html'] = content.text
                try:
                    item['word_count'] = int(content.attrib['wordcount'])
                except KeyError:
                    pass
            else:
                rendition = self.parse_remote_content(content)
                item['renditions'][rendition['rendition']] = rendition

    def parse_inline_content(self, tree, ns=XHTML):
        html = tree.find(self.qname('html', ns))
        body = html.find(self.qname('body', ns))
        elements = []
        for elem in body:
            if elem.text:
                tag = elem.tag.rsplit('}')[1]
                elements.append('<%s>%s</%s>' % (tag, elem.text, tag))

        # If there is a single p tag then replace the line feeds with breaks
        if len(elements) == 1 and body[0].tag.rsplit('}')[1] == 'p':
            elements[0] = elements[0].replace('\n    ', '</p><p>').replace('\n', '<br/>')

        content = dict()
        content['contenttype'] = tree.attrib['contenttype']
        if len(elements) > 0:
            content['content'] = "\n".join(elements)
        elif body.text:
            content['content'] = '<pre>' + body.text + '</pre>'
            content['format'] = CONTENT_TYPE.PREFORMATTED
        return content

    def parse_remote_content(self, tree):
        content = dict()
        content['residRef'] = tree.attrib.get('residref')
        content['sizeinbytes'] = int(tree.attrib.get('size', '0'))
        content['rendition'] = tree.attrib['rendition'].split(':')[1]
        content['mimetype'] = tree.attrib['contenttype']
        content['href'] = tree.attrib.get('href', None)
        return content

    def datetime(self, string):
        try:
            return datetime.datetime.strptime(string, '%Y-%m-%dT%H:%M:%S.000Z')
        except ValueError:
            return arrow.get(string).datetime

    def get_literal_name(self, item):
        """Get name for item with fallback to literal attribute if name is not provided."""
        name = item.find(self.qname('name'))
        return name.text if name is not None else item.attrib.get('literal')


register_feed_parser(NewsMLTwoFeedParser.NAME, NewsMLTwoFeedParser())
