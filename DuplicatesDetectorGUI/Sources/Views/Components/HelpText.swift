import SwiftUI

/// Contextual help text displayed below a control.
///
/// Single line of ``DDTypography/label`` in ``DDColors/textMuted``,
/// providing brief explanations for technical settings.
struct HelpText: View {
    let text: String
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        Text(text)
            .font(DDTypography.label)
            .foregroundStyle(ddColors.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
