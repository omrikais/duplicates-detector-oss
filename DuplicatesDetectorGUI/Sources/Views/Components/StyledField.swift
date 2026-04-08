import SwiftUI

/// Styled text field with subtle inset background.
///
/// Shared text field pattern used across all tab views:
/// plain text field style + sm padding + surface0 background + small radius.
struct StyledField: ViewModifier {
    func body(content: Content) -> some View {
        content
            .textFieldStyle(.plain)
            .padding(DDSpacing.sm)
            .background(DDColors.surface0.opacity(0.5), in: RoundedRectangle(cornerRadius: DDRadius.small))
    }
}

extension View {
    func styledField() -> some View {
        modifier(StyledField())
    }
}
