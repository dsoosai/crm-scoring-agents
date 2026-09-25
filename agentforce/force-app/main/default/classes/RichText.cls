/**
 * Turns model output into the small HTML subset that rich text fields accept, and back to plain text
 * for grounding. Prompts ask for HTML; this also copes with Markdown or stray code fences.
 */
public with sharing class RichText {

    public static String toHtml(String modelText) {
        if (String.isBlank(modelText)) {
            return '';
        }
        String s = modelText.trim();
        s = s.replaceAll('^```[a-zA-Z]*\\s*', '').replaceAll('\\s*```$', '').trim();
        if (Pattern.compile('(?i)<(p|ul|ol|li|h[1-6]|b|strong|table|br)\\b').matcher(s).find()) {
            return s;
        }
        return markdownToHtml(s);
    }

    public static String toPlain(String html) {
        if (String.isBlank(html)) {
            return '';
        }
        String s = html.replaceAll('(?i)<li>', '\n- ').replaceAll('(?i)</(p|h[1-6]|ul|ol|tr)>', '\n').replaceAll('(?i)<br\\s*/?>', '\n');
        s = s.stripHtmlTags();
        return s.replaceAll('\n{3,}', '\n\n').trim();
    }

    @TestVisible
    private static String markdownToHtml(String md) {
        List<String> out = new List<String>();
        Boolean inList = false;
        for (String raw : md.split('\n')) {
            String line = raw.trim();
            Boolean bullet = line.startsWith('- ') || line.startsWith('* ');
            if (!bullet && inList) {
                out.add('</ul>');
                inList = false;
            }
            if (String.isBlank(line)) {
                continue;
            }
            line = line.escapeHtml4().replaceAll('\\*\\*(.+?)\\*\\*', '<b>$1</b>');
            if (bullet) {
                if (!inList) {
                    out.add('<ul>');
                    inList = true;
                }
                out.add('<li>' + line.substring(2).trim() + '</li>');
            } else if (line.startsWith('#')) {
                out.add('<p><b>' + line.replaceAll('^#+\\s*', '') + '</b></p>');
            } else {
                out.add('<p>' + line + '</p>');
            }
        }
        if (inList) {
            out.add('</ul>');
        }
        return String.join(out, '');
    }
}
