//! Native resize regression for the collection's floating CLAP editors.
//!
//! A floating window has no host parent to resize. Relaying each native resize through
//! `host.gui.request_resize` needlessly wakes and redraws the player on every drag event, defeating
//! its deliberately throttled service cadence. This checks the real bundle, not panel layout.
//! Windows-only driver; the wrapper repair is platform-independent. Linux/macOS native resizing
//! and embedded DAW resizing still require manual verification.

#[cfg(target_os = "windows")]
mod windows {
    use std::{collections::BTreeSet, path::PathBuf};

    use mxm_player::engine::Engine;

    const RESIZE_INVENTORY: &[(&str, bool)] = &[
        ("mxm-mono-00", false),
        ("mxm-mono-01", false),
        ("mxm-mono-02", false),
        ("mxm-mono-03", false),
        ("mxm-mono-08", false),
        ("mxm-mono-pr1", false),
        ("mxm-poly-06", false),
        ("mxm-para-07", false),
        ("mxm-chorus-06", true),
        ("mxm-folded-spring", true),
        ("mxm-bucket-delay", true),
        ("mxm-shimmer", true),
        ("mxm-classic-verb", true),
        ("mxm-grain-fx", true),
        ("mxm-fx-convolution", true),
        ("mxm-fx-curve", true),
        ("mxm-fx-delay", true),
        ("mxm-creative-sampler", false),
        ("mxm-drum-machine", false),
        ("mxm-model-drums", false),
    ];
    const HEADLESS_BUNDLES: &[&str] = &[];

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetCurrentThreadId() -> u32;
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn EnumThreadWindows(
            thread: u32,
            callback: unsafe extern "system" fn(isize, isize) -> i32,
            data: isize,
        ) -> i32;
        fn GetClassNameW(window: isize, name: *mut u16, len: i32) -> i32;
        fn IsWindowVisible(window: isize) -> i32;
        fn SetWindowPos(
            window: isize,
            after: isize,
            x: i32,
            y: i32,
            width: i32,
            height: i32,
            flags: u32,
        ) -> i32;
        fn GetWindowRect(window: isize, rect: *mut NativeRect) -> i32;
    }

    #[repr(C)]
    #[derive(Default)]
    struct NativeRect {
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    }

    unsafe extern "system" fn collect(window: isize, data: isize) -> i32 {
        let mut name = [0_u16; 128];
        let len = unsafe { GetClassNameW(window, name.as_mut_ptr(), name.len() as i32) };
        if len > 0
            && unsafe { IsWindowVisible(window) } != 0
            && String::from_utf16_lossy(&name[..len as usize]).starts_with("Baseview-")
        {
            unsafe { &mut *(data as *mut Vec<isize>) }.push(window);
        }
        1
    }

    fn editor_windows() -> Vec<isize> {
        let mut windows = Vec::new();
        // Enumerate this test thread only: never touch another test's or the user's editor.
        unsafe {
            EnumThreadWindows(
                GetCurrentThreadId(),
                collect,
                std::ptr::from_mut(&mut windows) as isize,
            );
        }
        windows
    }

    #[test]
    fn inventory_matches_every_shipped_bundle_declaration() {
        let inventory: BTreeSet<_> = RESIZE_INVENTORY
            .iter()
            .map(|(name, _)| *name)
            .chain(HEADLESS_BUNDLES.iter().copied())
            .collect();
        assert_eq!(
            inventory.len(),
            RESIZE_INVENTORY.len() + HEADLESS_BUNDLES.len(),
            "native-resize/headless inventory contains a duplicate"
        );
        let shipped: BTreeSet<_> = include_str!("../../../bundler.toml")
            .lines()
            .filter_map(|line| line.strip_prefix('[')?.strip_suffix(']'))
            .collect();
        assert_eq!(
            inventory, shipped,
            "native-resize inventory must match every shipped bundle declaration"
        );
    }

    /// Run after bundling all twenty shipped editors, with no other native-window test on this thread:
    /// `cargo test -p mxm-player --test editor_resize -- --ignored --nocapture`
    #[test]
    #[ignore = "creates real editor windows; requires Windows desktop and all twenty bundles"]
    fn floating_resizes_do_not_round_trip_through_the_host() {
        let bundled = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../target/bundled");
        for &(name, effect) in RESIZE_INVENTORY {
            let path = bundled.join(format!("{name}.clap"));
            assert!(
                path.exists(),
                "bundle {name} before running this native test"
            );
            let mut engine = Engine::new();
            let id = format!("dk.mxm.{name}");
            if effect {
                engine.add_fx(&path, &id).expect("load effect bundle");
            } else {
                engine.load(&path, &id).expect("load instrument bundle");
            }
            for attempt in 0..2 {
                let before = editor_windows();
                if effect {
                    engine.open_fx_editor(0, None).expect("open effect editor");
                } else {
                    engine.open_editor(None).expect("open instrument editor");
                }
                let new: Vec<_> = editor_windows()
                    .into_iter()
                    .filter(|window| !before.contains(window))
                    .collect();
                assert_eq!(new.len(), 1, "{name}: identify exactly one new editor");
                let window = new[0];
                engine.service_editor(); // Ignore creation notifications, not resize notifications.
                let mut round_trips = 0;
                for step in 0..24 {
                    let width = 1000 + step * 3;
                    let height = 760 + step * 2;
                    // SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE; synchronous native WM_SIZE.
                    assert_ne!(
                        unsafe {
                            SetWindowPos(window, 0, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010)
                        },
                        0
                    );
                    round_trips += usize::from(engine.service_editor());
                    let mut actual = NativeRect::default();
                    assert_ne!(unsafe { GetWindowRect(window, &mut actual) }, 0);
                    assert_eq!(actual.right - actual.left, width, "{name}: width refused");
                    assert_eq!(actual.bottom - actual.top, height, "{name}: height refused");
                }
                // Close before asserting, including on the deliberately broken baseline.
                if effect {
                    engine.close_editor_for(mxm_player::engine::editor::EditorTarget::Fx(0));
                } else {
                    engine.close_editor();
                }
                println!("{name}, open {attempt}: {round_trips}/24 resizes woke the host");
                assert_eq!(
                    round_trips, 0,
                    "{name}: floating resize must stay in its own window"
                );
            }
        }
    }
}
